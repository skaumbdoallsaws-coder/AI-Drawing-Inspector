"""Builds the per-revision Feature Intent Map.

Output document at parts/{pn}/{rev}/{pn}_feature_intent_map.json:

    {
      "schemaVersion": "feature-intent-map-1.0.0",
      "partNumber":    "1030034",
      "revision":      "revC",
      "generatedAtUtc":"...",
      "summary":       {totalFeatures, regionMappedCount, curatedCount,
                        editTargetCount, propagationCount, referenceCount},
      "features":      [ {Entry}, ... ]
    }

Each entry:

    {
      "cadFeatureId":   "ice_boss_extrude1",
      "solidWorksName": "Boss-Extrude1",
      "regionId":       "propeller",
      "regionLabel":    "Propeller",
      "physicalName":   "single propeller blade",
      "featureRole":    "creates the blade body",
      "editRole":       "primary_edit_target" | "propagation" |
                        "reference" | "unknown",
      "controls": [
        {
          "parameter":        "depth1_mm",
          "displayName":      "blade thickness",
          "units":            "mm",
          "physicalMeaning":  "Increasing this makes the blade thicker..."
        }
      ],
      "downstreamFeatures": [ "cirpattern1", ... ],
      "reviewed":   false,
      "confidence": "low" | "medium" | "high"
    }

Curator preservation: an existing on-disk entry with reviewed=true
is copied verbatim and downstream regeneration cannot replace its
physicalName / controls / etc. Reviewed entries are still re-keyed
by cadFeatureId so a feature renamed across revisions falls back
to heuristics gracefully.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import rules as _rules


SCHEMA_VERSION = "feature-intent-map-1.0.0"
FEATURE_INTENT_MAP_FILENAME = "{pn}_feature_intent_map.json"

EDIT_ROLE_VALUES = _rules.EDIT_ROLES


def feature_intent_map_path(library_dir: Path, pn: str, revision: str) -> Path:
    """Canonical on-disk path. parts/{pn}/{rev}/{pn}_feature_intent_map.json."""
    return library_dir / "parts" / pn / revision / FEATURE_INTENT_MAP_FILENAME.format(pn=pn)


def load_feature_intent_map(library_dir: Path, pn: str, revision: str) -> Optional[Dict[str, Any]]:
    """Defensive read: returns None on missing or malformed file so
    callers can fall back to technical-only language without
    exception handling."""
    p = feature_intent_map_path(library_dir, pn, revision)
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def write_feature_intent_map(library_dir: Path, pn: str, revision: str, doc: Dict[str, Any]) -> Path:
    """Atomic write (.tmp + replace). Mirrors the semantic_regions
    builder's write helper so the two sidecars have identical
    durability characteristics."""
    out_path = feature_intent_map_path(library_dir, pn, revision)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    tmp.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    tmp.replace(out_path)
    return out_path


def _load_feature_colors(library_dir: Path, pn: str, revision: str) -> List[Dict[str, Any]]:
    p = library_dir / "parts" / pn / revision / f"{pn}_feature_colors.json"
    if not p.exists():
        return []
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return []
    feats = doc.get("features") if isinstance(doc, dict) else None
    return feats if isinstance(feats, list) else []


def _load_semantic_regions(library_dir: Path, pn: str, revision: str) -> Optional[Dict[str, Any]]:
    """Best-effort. Imported lazily so feature_intent doesn't take a
    hard dep on the semantic_regions package being present at import
    time (it always is in this project, but the contract is cleaner)."""
    try:
        from ai_inspector.semantic_regions import semantic_regions_path
    except Exception:
        return None
    p = semantic_regions_path(library_dir, pn, revision)
    if not p.exists():
        return None
    try:
        doc = json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def _index_regions_by_cad_feature(regions_doc: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    """{cadFeatureId -> {regionId, regionLabel}}. Returns empty when
    the regions doc is missing -- caller handles the no-region case."""
    out: Dict[str, Dict[str, str]] = {}
    if not isinstance(regions_doc, dict):
        return out
    regions = regions_doc.get("regions") or []
    if not isinstance(regions, list):
        return out
    for r in regions:
        if not isinstance(r, dict):
            continue
        region_id = str(r.get("regionId") or "")
        label     = str(r.get("label") or region_id)
        cad_targets = (r.get("cadTargets") or {})
        cad_ids = cad_targets.get("cadFeatureIds") if isinstance(cad_targets, dict) else None
        if not isinstance(cad_ids, list):
            cad_ids = r.get("sourceFeatures") if isinstance(r.get("sourceFeatures"), list) else []
        for cid in cad_ids:
            if isinstance(cid, str) and cid and cid not in out:
                out[cid] = {"regionId": region_id, "regionLabel": label}
    return out


def _index_existing_entries_by_cad_feature(existing_doc: Optional[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    """{cadFeatureId -> existing entry dict}. Empty when no prior map
    exists. Used by the preservation pass to copy reviewed=true
    entries forward."""
    out: Dict[str, Dict[str, Any]] = {}
    if not isinstance(existing_doc, dict):
        return out
    feats = existing_doc.get("features") if isinstance(existing_doc.get("features"), list) else None
    if not feats:
        return out
    for entry in feats:
        if not isinstance(entry, dict):
            continue
        cid = entry.get("cadFeatureId")
        if isinstance(cid, str) and cid:
            out[cid] = entry
    return out


def _downstream_for_region(region_id: str, cad_id: str, region_index: Dict[str, Dict[str, str]],
                           all_features: List[Dict[str, Any]]) -> List[str]:
    """For a primary-edit-target boss/extrude/etc in some region,
    list any pattern/mirror features in the SAME region that will
    propagate the edit. Heuristic: feature is in same region AND its
    name/type matches the pattern/mirror keywords. Empty when the
    feature itself IS the pattern, or there is no region info."""
    if not region_id:
        return []
    out: List[str] = []
    for f in all_features:
        if not isinstance(f, dict):
            continue
        other_id = f.get("cad_feature_id") or f.get("glb_node_name")
        if not isinstance(other_id, str) or other_id == cad_id:
            continue
        other_region = region_index.get(other_id)
        if not other_region or other_region.get("regionId") != region_id:
            continue
        other_name = str(f.get("sw_name") or "")
        other_type = str(f.get("type") or "")
        blob = (other_name + " " + other_type + " " + other_id).lower()
        if any(kw in blob for kw in (
                "cirpattern", "linpattern", "mirrorsolid", "mirrorrefsurf",
                "mirrorpattern", "tablepattern", "curvedpattern",
                "sketchpattern", "fillpattern", "pattern", "mirror")):
            out.append(other_id)
    return out


def build_draft_intent_map(library_dir: Path, pn: str, revision: str) -> Dict[str, Any]:
    """Build the intent map from semantic_regions + feature_colors.
    Preserves reviewed=true entries from any existing map on disk.

    Always returns a well-formed doc. When feature_colors.json is
    missing the doc has an empty features[] -- callers can detect
    that and fall back to technical-only language. Never raises.
    """
    features_raw  = _load_feature_colors(library_dir, pn, revision)
    regions_doc   = _load_semantic_regions(library_dir, pn, revision)
    existing_doc  = load_feature_intent_map(library_dir, pn, revision)

    region_index   = _index_regions_by_cad_feature(regions_doc)
    existing_index = _index_existing_entries_by_cad_feature(existing_doc)

    out_features: List[Dict[str, Any]] = []
    edit_count = prop_count = ref_count = unknown_count = 0
    curated_count = 0
    region_mapped = 0

    for feat in features_raw:
        if not isinstance(feat, dict):
            continue
        cid = feat.get("cad_feature_id") or feat.get("glb_node_name")
        if not isinstance(cid, str) or not cid:
            continue
        sw_name = str(feat.get("sw_name") or feat.get("display_label") or cid)
        sw_type = str(feat.get("type") or "")

        # Preserve reviewed=true entries verbatim.
        prior = existing_index.get(cid)
        if isinstance(prior, dict) and prior.get("reviewed") is True:
            out_features.append(prior)
            curated_count += 1
            role = str(prior.get("editRole") or "unknown")
            if role == "primary_edit_target": edit_count    += 1
            elif role == "propagation":       prop_count    += 1
            elif role == "reference":         ref_count     += 1
            else:                              unknown_count += 1
            if prior.get("regionId"): region_mapped += 1
            continue

        # Heuristic build.
        region_info = region_index.get(cid)
        region_id    = region_info["regionId"]    if region_info else ""
        region_label = region_info["regionLabel"] if region_info else ""

        rule_out = _rules.classify(sw_name, sw_type, cid, region_label)
        edit_role  = rule_out.get("editRole") or "unknown"
        controls   = rule_out.get("controls") or []
        physical   = rule_out.get("physicalName") or ""
        role_text  = rule_out.get("featureRole") or ""

        downstream: List[str] = []
        if edit_role == "primary_edit_target":
            downstream = _downstream_for_region(region_id, cid, region_index, features_raw)

        # Confidence is "high" when we matched a rule AND have region
        # context, "medium" when we matched a rule without region,
        # "low" when no rule fired (fallback unknown entry).
        if edit_role == "unknown" and not controls:
            confidence = "low"
        elif region_id:
            confidence = "high"
        else:
            confidence = "medium"

        out_features.append({
            "cadFeatureId":       cid,
            "solidWorksName":     sw_name,
            "regionId":           region_id,
            "regionLabel":        region_label,
            "physicalName":       physical,
            "featureRole":        role_text,
            "editRole":           edit_role,
            "controls":           controls,
            "downstreamFeatures": downstream,
            "reviewed":           False,
            "confidence":         confidence,
        })

        if edit_role == "primary_edit_target": edit_count    += 1
        elif edit_role == "propagation":       prop_count    += 1
        elif edit_role == "reference":         ref_count     += 1
        else:                                   unknown_count += 1
        if region_id: region_mapped += 1

    summary = {
        "totalFeatures":      len(out_features),
        "regionMappedCount":  region_mapped,
        "curatedCount":       curated_count,
        "editTargetCount":    edit_count,
        "propagationCount":   prop_count,
        "referenceCount":     ref_count,
        "unknownCount":       unknown_count,
    }
    return {
        "schemaVersion":  SCHEMA_VERSION,
        "partNumber":     pn,
        "revision":       revision,
        "generatedAtUtc": _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "summary":        summary,
        "features":       out_features,
    }
