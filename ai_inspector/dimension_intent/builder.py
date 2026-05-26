"""Builds the per-revision Dimension Intent Map.

Output document at parts/{pn}/{rev}/{pn}_dimension_intent_map.json:

    {
      "schemaVersion": "dimension-intent-map-0.1.0",
      "partNumber":    "1030035",
      "revision":      "revA",
      "generatedAtUtc":"...",
      "summary": {
        "mappingCount":          N,
        "reviewedCount":         M,
        "highConfidenceCount":   H,
        "candidateCount":        C
      },
      "mappings": [ {Mapping}, ... ]
    }

Each mapping carries enough metadata for both the curator UI and the
Sage handoff path to surface a single exact CAD dimension when the
operator's phrase resolves to one:

    {
      "mappingId":            "wheel_tire:revolution_revolve2:D1@Sketch7",
      "physicalName":         "wheel outside diameter",
      "semanticRegionId":     "wheel_tire",
      "semanticRegionLabel":  "Wheel / tire",
      "cadFeatureId":         "revolution_revolve2",
      "sourceFeature":        "Revolve2",
      "ownerFeature":         "Sketch7",
      "ownerType":            "sketch" | "feature",
      "dimensionShortName":   "D1",
      "dimensionFullName":    "D1@Sketch7",
      "cadValueMm":           87.266,
      "dimensionType":        "diameter" | "radius" | "linear" | "angle",
      "drawingDimensionId":   "Drawing View1/D1",   // {viewName}/{annotationName}
      "drawingValueMm":       87.266,
      "drawingDescription":   "wheel outside diameter",
      "matchConfidence":      "high" | "medium" | "low",
      "reviewed":             false,
      "evidence":             ["value_match", "region_match", ...]
    }

Curator preservation: an existing on-disk mapping with reviewed=true
is copied verbatim on re-draft and downstream regeneration cannot
replace its physicalName / cad+drawing bindings. Reviewed mappings
are keyed by mappingId so a feature rename across revisions falls
back to heuristics gracefully.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from . import matcher as _matcher


SCHEMA_VERSION = "dimension-intent-map-0.1.0"
DIMENSION_INTENT_MAP_FILENAME = "{pn}_dimension_intent_map.json"

# Lowercase machine-readable confidence values. UI uses these to
# decide whether to surface a mapping by default (high/medium) vs
# only on operator drill-down (low).
MATCH_CONFIDENCE_VALUES = ("high", "medium", "low")


def dimension_intent_map_path(library_dir: Path, pn: str, revision: str) -> Path:
    """Canonical on-disk path. parts/{pn}/{rev}/{pn}_dimension_intent_map.json."""
    return library_dir / "parts" / pn / revision / DIMENSION_INTENT_MAP_FILENAME.format(pn=pn)


def load_dimension_intent_map(library_dir: Path, pn: str, revision: str) -> Optional[Dict[str, Any]]:
    """Defensive read. Returns None on missing or malformed JSON so
    callers can fall back to "no map yet" without exception handling."""
    p = dimension_intent_map_path(library_dir, pn, revision)
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def write_dimension_intent_map(library_dir: Path, pn: str, revision: str, doc: Dict[str, Any]) -> Path:
    """Atomic write (.tmp + replace), mirroring the feature_intent +
    sketch_intent writers so all three sidecars share durability
    characteristics."""
    out_path = dimension_intent_map_path(library_dir, pn, revision)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return out_path


# ── PUT validation ─────────────────────────────────────────────────

_REQUIRED_MAPPING_FIELDS = (
    "mappingId",
    "cadFeatureId",
    "ownerFeature",
    "dimensionShortName",
    "dimensionFullName",
    "matchConfidence",
)


def validate_mapping(mapping: Any) -> List[str]:
    """Return a list of validation errors for ONE mapping object. Empty
    list means valid. Pure -- never raises; the server endpoint joins
    these into a 400 detail."""
    errors: List[str] = []
    if not isinstance(mapping, dict):
        errors.append("mapping must be an object")
        return errors
    for field in _REQUIRED_MAPPING_FIELDS:
        val = mapping.get(field)
        if not isinstance(val, str) or not val.strip():
            errors.append(f"missing required string field: {field}")
    mc = mapping.get("matchConfidence")
    if isinstance(mc, str) and mc not in MATCH_CONFIDENCE_VALUES:
        errors.append(
            f"matchConfidence must be one of {list(MATCH_CONFIDENCE_VALUES)}; got {mc!r}"
        )
    for numeric in ("cadValueMm", "drawingValueMm"):
        if numeric in mapping and mapping[numeric] is not None:
            try:
                float(mapping[numeric])
            except (TypeError, ValueError):
                errors.append(f"{numeric} must be numeric or null")
    return errors


# ── Source loaders (best-effort; missing files return empty) ───────

def _load_json(path: Path) -> Optional[Dict[str, Any]]:
    if not path.exists():
        return None
    try:
        d = json.loads(path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return d if isinstance(d, dict) else None


def _load_part_json(library_dir: Path, pn: str, revision: str) -> Optional[Dict[str, Any]]:
    """Look for part.json under the revision's bridge package OR the
    rev directory itself. Returns the parsed dict, or None when
    nothing is found. cadDimensions are read directly from this doc
    once the extractor supports them."""
    rev_dir = library_dir / "parts" / pn / revision
    # 1) rev_dir / part.json (forward-looking convention)
    direct = rev_dir / "part.json"
    if direct.exists():
        doc = _load_json(direct)
        if doc is not None:
            return doc
    # 2) rev_dir / {pn}.json (current convention -- some revs ship the
    #    extractor doc under this name)
    pn_named = rev_dir / f"{pn}.json"
    if pn_named.exists():
        doc = _load_json(pn_named)
        if doc is not None:
            return doc
    return None


def _load_drawing_map(library_dir: Path, pn: str) -> Optional[Dict[str, Any]]:
    """{pn}_drawing_map.json at the library root carries the drawing
    annotations -- each one already names the sketch (featureName) +
    short name (annotationName) + value. Best-effort: missing means
    we cannot do drawing<->cad pairing this pass."""
    p = library_dir / f"{pn}_drawing_map.json"
    return _load_json(p)


def _load_dimension_descriptions(library_dir: Path, pn: str) -> Dict[str, str]:
    """{pn}_dimension_descriptions.json keys descriptions by
    '{viewName}/{annotationName}'. Returns a flat dict; empty when
    the file is missing or malformed."""
    p = library_dir / f"{pn}_dimension_descriptions.json"
    doc = _load_json(p)
    if not isinstance(doc, dict):
        return {}
    descs = doc.get("descriptions")
    if not isinstance(descs, dict):
        return {}
    return {str(k): str(v) for k, v in descs.items() if isinstance(v, str)}


def _load_semantic_regions(library_dir: Path, pn: str, revision: str) -> Optional[Dict[str, Any]]:
    try:
        from ai_inspector.semantic_regions import semantic_regions_path
    except Exception:
        return None
    p = semantic_regions_path(library_dir, pn, revision)
    return _load_json(p)


def _load_sketch_intent(library_dir: Path, pn: str, revision: str) -> Optional[Dict[str, Any]]:
    try:
        from ai_inspector.sketch_intent import sketch_dimension_intent_map_path
    except Exception:
        return None
    p = sketch_dimension_intent_map_path(library_dir, pn, revision)
    return _load_json(p)


# ── Normalisation helpers ──────────────────────────────────────────

def _index_regions_by_cad_feature(regions_doc: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """{cadFeatureId -> {regionId, regionLabel}}. Mirrors the helper
    in feature_intent/builder.py; the duplication is intentional so
    this module has no hard dep on feature_intent internals."""
    out: Dict[str, Dict[str, str]] = {}
    if not isinstance(regions_doc, dict):
        return out
    for r in regions_doc.get("regions") or []:
        if not isinstance(r, dict):
            continue
        region_id = str(r.get("regionId") or "")
        label = str(r.get("label") or region_id)
        cad_targets = (r.get("cadTargets") or {})
        cad_ids = cad_targets.get("cadFeatureIds") if isinstance(cad_targets, dict) else None
        if not isinstance(cad_ids, list):
            cad_ids = r.get("sourceFeatures") if isinstance(r.get("sourceFeatures"), list) else []
        for cid in cad_ids:
            if isinstance(cid, str) and cid and cid not in out:
                out[cid] = {"regionId": region_id, "regionLabel": label}
    return out


def _extract_cad_dimensions(part_doc: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pull part.json `cadDimensions` array if present. Returns a
    sanitised list -- entries that miss the required identity fields
    are dropped silently. Empty list when the extractor has not yet
    added the array (current state for most parts)."""
    if not isinstance(part_doc, dict):
        return []
    raw = part_doc.get("cadDimensions")
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for entry in raw:
        if not isinstance(entry, dict):
            continue
        full = entry.get("dimensionFullName")
        short = entry.get("dimensionShortName")
        owner = entry.get("ownerFeature")
        if not (isinstance(full, str) and full.strip()
                and isinstance(short, str) and short.strip()
                and isinstance(owner, str) and owner.strip()):
            continue
        out.append(entry)
    return out


def _extract_drawing_dims(drawing_map: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Flatten drawing_map sheets[].views[].annotations[] into a list of
    normalized drawing-dimension records. Only annotations that carry
    a dimensionValue are kept (notes, balloons, center marks are
    filtered). Values normalised to mm (drawing_map stores meters)."""
    out: List[Dict[str, Any]] = []
    if not isinstance(drawing_map, dict):
        return out
    for sheet in drawing_map.get("sheets") or []:
        if not isinstance(sheet, dict):
            continue
        for view in sheet.get("views") or []:
            if not isinstance(view, dict):
                continue
            view_name = str(view.get("viewName") or "")
            for ann in view.get("annotations") or []:
                if not isinstance(ann, dict):
                    continue
                if ann.get("dimensionValue") is None:
                    continue
                short = str(ann.get("annotationName") or "").strip()
                owner = str(ann.get("featureName") or "").strip()
                try:
                    value_m = float(ann.get("dimensionValue"))
                except (TypeError, ValueError):
                    continue
                drawing_id = f"{view_name}/{short}" if view_name and short else short
                out.append({
                    "drawingDimensionId": drawing_id,
                    "viewName":           view_name,
                    "annotationName":     short,
                    "ownerFeature":       owner,
                    "valueMm":            value_m * 1000.0,
                    "dimensionType":      _matcher.canonical_dimension_type(
                        str(ann.get("dimensionType") or "")
                    ),
                    "isReference":        bool(ann.get("isReference") or False),
                })
    return out


# ── Mapping builders ───────────────────────────────────────────────

def _mapping_id(region_id: str, cad_feature_id: str, dim_full_name: str) -> str:
    """Stable mapping key. Region first so re-classifying a feature
    across regions produces a new id (the old reviewed entry survives
    in-place under its prior region). Format mirrors the spec example."""
    region_part = region_id or "unknown_region"
    cad_part    = cad_feature_id or "unknown_feature"
    return f"{region_part}:{cad_part}:{dim_full_name}"


def _seed_from_sketch_intent(
    sketch_doc:        Optional[Dict[str, Any]],
    region_index:      Dict[str, Dict[str, str]],
) -> List[Dict[str, Any]]:
    """Build CAD-only candidate mappings from a sketch_intent doc
    when it exists. Each reviewed sketch-dim entry becomes one
    medium-confidence mapping with evidence: ['sketch_intent_reviewed'].
    Lets the operator get value out of the dimension-intent map BEFORE
    the extractor populates cadDimensions."""
    out: List[Dict[str, Any]] = []
    if not isinstance(sketch_doc, dict):
        return out
    dims = sketch_doc.get("dimensions")
    if not isinstance(dims, list):
        return out
    for entry in dims:
        if not isinstance(entry, dict):
            continue
        if entry.get("reviewed") is not True:
            continue
        cad_id      = str(entry.get("cadFeatureId") or "").strip()
        sw_name     = str(entry.get("solidWorksName") or "").strip()
        sketch_feat = str(entry.get("sketchFeature") or "").strip()
        short_name  = str(entry.get("dimensionShortName") or "").strip()
        if not (sketch_feat and short_name):
            continue
        full_name   = str(entry.get("dimensionFullName") or "").strip()
        if not full_name:
            full_name = f"{short_name}@{sketch_feat}"
        region_info = region_index.get(cad_id) or {}
        region_id   = region_info.get("regionId") or str(entry.get("regionId") or "").strip()
        region_lbl  = region_info.get("regionLabel") or str(entry.get("regionLabel") or "").strip()
        out.append({
            "mappingId":           _mapping_id(region_id, cad_id, full_name),
            "physicalName":        str(entry.get("displayName") or entry.get("physicalMeaning") or "").strip() or None,
            "semanticRegionId":    region_id or None,
            "semanticRegionLabel": region_lbl or None,
            "cadFeatureId":        cad_id or None,
            "sourceFeature":       sw_name or None,
            "ownerFeature":        sketch_feat,
            "ownerType":           "sketch",
            "dimensionShortName":  short_name,
            "dimensionFullName":   full_name,
            "cadValueMm":          None,
            "dimensionType":       _matcher.canonical_dimension_type(str(entry.get("controlType") or "")),
            "drawingDimensionId":  None,
            "drawingValueMm":      None,
            "drawingDescription":  None,
            "matchConfidence":     "medium",
            "reviewed":            False,
            "evidence":            ["sketch_intent_reviewed"],
        })
    return out


def _mappings_from_cad_dimensions(
    cad_dims:       List[Dict[str, Any]],
    region_index:   Dict[str, Dict[str, str]],
    drawing_dims:   List[Dict[str, Any]],
    descriptions:   Dict[str, str],
) -> List[Dict[str, Any]]:
    """Primary pass: cross-reference part.json cadDimensions with
    drawing_map drawing dims via the matcher. Each cad dim yields at
    most one mapping. When no drawing dim matches, the mapping is
    CAD-only with matchConfidence='low' (operator can still review)."""
    out: List[Dict[str, Any]] = []
    for cad in cad_dims:
        full       = str(cad.get("dimensionFullName") or "")
        short      = str(cad.get("dimensionShortName") or "")
        owner      = str(cad.get("ownerFeature") or "")
        owner_type = str(cad.get("ownerType") or "").strip().lower() or "sketch"
        cad_id     = str(cad.get("cadFeatureId") or "")
        sw_name    = str(cad.get("controllingFeature") or "")
        cad_value  = cad.get("valueMm")
        try:
            cad_value_f = float(cad_value) if cad_value is not None else None
        except (TypeError, ValueError):
            cad_value_f = None
        dim_type = _matcher.canonical_dimension_type(str(cad.get("dimensionType") or ""))

        region_info = region_index.get(cad_id) or {}
        region_id   = region_info.get("regionId") or ""
        region_lbl  = region_info.get("regionLabel") or ""

        pair = _matcher.find_drawing_match(
            cad_full_name=full,
            cad_owner=owner,
            cad_short_name=short,
            cad_value_mm=cad_value_f,
            cad_dimension_type=dim_type,
            region_label=region_lbl,
            drawing_dims=drawing_dims,
            descriptions=descriptions,
        )

        drawing_id    = None
        drawing_value = None
        drawing_desc  = None
        evidence      = list(pair.evidence)
        confidence    = pair.confidence
        if pair.matched:
            drawing_id    = pair.drawing.get("drawingDimensionId")
            drawing_value = pair.drawing.get("valueMm")
            drawing_desc  = descriptions.get(drawing_id) if drawing_id else None
        elif cad_value_f is not None:
            # Unmatched CAD dim with a numeric value is still a low-
            # confidence candidate the curator can review later.
            evidence = ["cad_only"]
            confidence = "low"
        else:
            evidence = ["cad_only"]
            confidence = "low"

        out.append({
            "mappingId":           _mapping_id(region_id, cad_id, full),
            "physicalName":        drawing_desc or None,
            "semanticRegionId":    region_id or None,
            "semanticRegionLabel": region_lbl or None,
            "cadFeatureId":        cad_id or None,
            "sourceFeature":       sw_name or None,
            "ownerFeature":        owner,
            "ownerType":           owner_type,
            "dimensionShortName":  short,
            "dimensionFullName":   full,
            "cadValueMm":          cad_value_f,
            "dimensionType":       dim_type,
            "drawingDimensionId":  drawing_id,
            "drawingValueMm":      drawing_value,
            "drawingDescription":  drawing_desc,
            "matchConfidence":     confidence,
            "reviewed":            False,
            "evidence":            evidence,
        })
    return out


def _mappings_from_drawing_only(
    drawing_dims:   List[Dict[str, Any]],
    descriptions:   Dict[str, str],
    existing_full_names: set,
) -> List[Dict[str, Any]]:
    """Fallback: when part.json has no cadDimensions but the drawing
    map carries annotations whose featureName+annotationName already
    name the sketch dim (which they almost always do), produce
    medium-confidence mappings keyed off the drawing side. These let
    the operator review + curate even before the extractor catches up."""
    out: List[Dict[str, Any]] = []
    for d in drawing_dims:
        owner = str(d.get("ownerFeature") or "").strip()
        short = str(d.get("annotationName") or "").strip()
        if not (owner and short):
            continue
        full = f"{short}@{owner}"
        if full in existing_full_names:
            continue
        drawing_id  = d.get("drawingDimensionId")
        description = descriptions.get(drawing_id) if drawing_id else None
        owner_type  = "sketch" if owner.lower().startswith("sketch") else "feature"
        confidence = "medium" if description else "low"
        evidence: List[str] = ["drawing_names_owner"]
        if description:
            evidence.append("drawing_description")
        out.append({
            "mappingId":           _mapping_id("", "", full),
            "physicalName":        description or None,
            "semanticRegionId":    None,
            "semanticRegionLabel": None,
            "cadFeatureId":        None,
            "sourceFeature":       None,
            "ownerFeature":        owner,
            "ownerType":           owner_type,
            "dimensionShortName":  short,
            "dimensionFullName":   full,
            "cadValueMm":          None,
            "dimensionType":       d.get("dimensionType") or "linear",
            "drawingDimensionId":  drawing_id,
            "drawingValueMm":      d.get("valueMm"),
            "drawingDescription":  description,
            "matchConfidence":     confidence,
            "reviewed":            False,
            "evidence":            evidence,
        })
    return out


def build_draft_dimension_intent_map(library_dir: Path, pn: str, revision: str) -> Tuple[Dict[str, Any], List[str]]:
    """Build a fresh dimension intent map for {pn}/{rev}. Returns
    (doc, warnings). Never raises -- missing source files turn into
    warning strings + empty/partial mappings.

    Preservation: every entry in any existing on-disk map with
    reviewed=true is copied verbatim into the new doc BEFORE the
    heuristic pass runs, and the heuristic pass does NOT produce a
    competing entry for the same mappingId. Operators can hand-edit
    physicalName / drawing bindings and the next re-draft will
    respect their work."""
    warnings: List[str] = []

    part_doc       = _load_part_json(library_dir, pn, revision)
    drawing_map    = _load_drawing_map(library_dir, pn)
    descriptions   = _load_dimension_descriptions(library_dir, pn)
    regions_doc    = _load_semantic_regions(library_dir, pn, revision)
    sketch_doc     = _load_sketch_intent(library_dir, pn, revision)
    existing_doc   = load_dimension_intent_map(library_dir, pn, revision)

    region_index   = _index_regions_by_cad_feature(regions_doc)
    cad_dims       = _extract_cad_dimensions(part_doc)
    drawing_dims   = _extract_drawing_dims(drawing_map)

    if not cad_dims:
        warnings.append(
            "cad_dimensions_missing: part.json has no cadDimensions; extractor support required"
        )
    if not drawing_dims:
        warnings.append(
            "drawing_dimensions_missing: no drawing_map annotations with dimensionValue; "
            "draft will skip drawing<->cad matches"
        )
    if not isinstance(regions_doc, dict):
        warnings.append("semantic_regions_missing: regions cannot anchor mappings to regions")

    # ── Preserve reviewed=true mappings verbatim ──────────────────
    preserved: List[Dict[str, Any]] = []
    preserved_ids: set = set()
    if isinstance(existing_doc, dict):
        for entry in existing_doc.get("mappings") or []:
            if isinstance(entry, dict) and entry.get("reviewed") is True:
                preserved.append(entry)
                mid = str(entry.get("mappingId") or "")
                if mid:
                    preserved_ids.add(mid)

    # ── Heuristic pass ────────────────────────────────────────────
    candidate_pool: List[Dict[str, Any]] = []
    if cad_dims:
        candidate_pool.extend(_mappings_from_cad_dimensions(
            cad_dims, region_index, drawing_dims, descriptions,
        ))
    else:
        # Seed from reviewed sketch_intent entries when available so
        # the curator has something useful before the extractor adds
        # cadDimensions.
        if sketch_doc is not None:
            candidate_pool.extend(_seed_from_sketch_intent(sketch_doc, region_index))

    # Drawing-only fallback always runs -- even when cadDimensions is
    # present, the drawing map may carry sketches the extractor missed.
    existing_full_names = {str(m.get("dimensionFullName") or "")
                            for m in (preserved + candidate_pool)
                            if isinstance(m, dict)}
    candidate_pool.extend(_mappings_from_drawing_only(
        drawing_dims, descriptions, existing_full_names,
    ))

    # Drop heuristic candidates whose mappingId collides with a
    # preserved entry -- the curator's work always wins.
    heuristic: List[Dict[str, Any]] = [
        m for m in candidate_pool
        if str(m.get("mappingId") or "") not in preserved_ids
    ]

    all_mappings = preserved + heuristic

    # Summary counts.
    summary = {
        "mappingCount":        len(all_mappings),
        "reviewedCount":       sum(1 for m in all_mappings if m.get("reviewed") is True),
        "highConfidenceCount": sum(1 for m in all_mappings if m.get("matchConfidence") == "high"),
        "candidateCount":      sum(1 for m in all_mappings if m.get("matchConfidence") in ("medium", "low")),
    }

    doc = {
        "schemaVersion":  SCHEMA_VERSION,
        "partNumber":     pn,
        "revision":       revision,
        "generatedAtUtc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "summary":        summary,
        "mappings":       all_mappings,
    }
    return doc, warnings
