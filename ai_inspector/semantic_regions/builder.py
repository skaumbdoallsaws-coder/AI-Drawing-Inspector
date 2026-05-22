"""Top-level semantic-region builder.

Orchestrates GLB inspection + classification + grouping into the
{pn}_semantic_regions.json contract documented in the MVP spec.

Forward-compat: the schema is designed to be the bridge between
user language in InspectorPro ("make the top wing 2 inches thicker")
and controlled CAD edits in SOLIDWORKS Sage. The MVP only populates
visual + sourceFeature data, but the dataclass already carries
empty placeholders for the CAD-edit orchestration fields the
dependency extractor will fill in later. Schema version is bumped
when fields are added; readers should ignore unknown fields.

Output document:

    {
      "schemaVersion":   "part-semantic-regions-1.1.0",
      "partNumber":      "1030034",
      "revision":        "revB",
      "generatedAtUtc":  "...",
      "axisFrame":       { ... },     # frame auto-detection metadata
      "summary":         { totalNodes, regionCount, reviewedCount, ... },
      "regions":         [ {Region}, ... ]
    }

Each region (schema 1.3.0):

    {
      "regionId":      "top_wing",
      "label":         "Top wing",
      "aliases":       ["upper wing", ...],
      "glbNodes":      [...],
      "sourceFeatures":[...],
      "confidence":    "high" | "medium" | "low",
      "reviewed":      false,
      "requiresReview": true,
      "editReadiness": "unknown" | "not_ready" | "candidate" | "ready",
      "visualTargets": {
        "glbNodes": [...]              # mirrors region.glbNodes
      },
      "cadTargets": {
        "sourceFeatures":   [...],     # SW-visible feature names (sw_name)
        "cadFeatureIds":    [...],     # stable SolidWorks identifiers (cad_feature_id);
                                       # schema 1.3.0+, populated from feature_colors.json
        "upstreamFeatures": [],        # MVP: empty; needs dep extractor
        "sketches":         [],        # MVP: empty; needs dep extractor
        "planes":           [],        # MVP: empty; needs dep extractor
        "dimensions":       []         # MVP: empty; needs dep extractor
      },
      "editableParameters": [],        # MVP: empty; needs param extractor

      # Schema 1.2.0: future-facing CAD-EDIT PLANNING scaffolding.
      # Each placementSurface describes a candidate face on which Sage
      # could place sketches / extrudes / holes once the surface
      # extractor lands. The MVP leaves this empty -- no face IDs are
      # extracted today.
      "placementSurfaces": [
        # {
        #   "faceId":         "",          # SolidWorks face persistent id
        #   "sourceFeature":  "",          # owning feature name
        #   "role":           "primary_sketch_surface" |
        #                     "reference_surface" |
        #                     "do_not_edit",
        #   "surfaceType":    "planar" | "cylindrical" | "curved" | "unknown",
        #   "normal":         [nx, ny, nz],
        #   "origin":         [ox, oy, oz],
        #   "xAxis":          [...],
        #   "yAxis":          [...],
        #   "span":           {"x": ..., "y": ..., "z": null, "unit": "mm"},
        #   "safeMargins":    {...},
        #   "confidence":     "low" | "medium" | "high"
        # }
      ],
      # placementCapabilities answers "what classes of CAD edits could
      # Sage plan against this region once a surface is selected?".
      # MVP default: ["reference_only"] -- the region can be cited /
      # highlighted but no edit class is wired up yet. The dependency
      # + parameter extractors will widen this to include
      # sketch_on_face, extruded_boss, extruded_cut, hole_wizard_pattern.
      "placementCapabilities": ["reference_only"],

      "unmappedGlbNodes": [],          # schema 1.3.0+: glbNodes that
                                       # had no feature_colors mapping;
                                       # surfaced in notes too

      "source":        "ai_inspector.semantic_regions.builder/1.3.0-mvp",
      "notes":         "AI-proposed grouping; operator should verify."
    }
"""

from __future__ import annotations

import datetime as _dt
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .glb_inspect import GlbNode, GlbSummary, inspect_glb
from .rules import (
    LABELS,
    AxisFrame,
    classify_node_aircraft,
    detect_axis_frame,
    fallback_bucket_id,
    fallback_bucket_label,
)


SCHEMA_VERSION = "part-semantic-regions-1.3.0"
SEMANTIC_REGIONS_FILENAME = "{pn}_semantic_regions.json"

# Pinned source string so an operator can grep for AI-generated regions
# vs operator-curated ones (the curator tool will overwrite this string
# when it locks a region).
_DEFAULT_REGION_SOURCE = "ai_inspector.semantic_regions.builder/1.3.0-mvp"

# Allowed values for region.editReadiness. The MVP only ever emits
# "not_ready" because we lack sketch/plane/dimension/parameter data
# the dependency extractor will populate later. Reserved literals so
# downstream code can pattern-match without typos.
EDIT_READINESS_VALUES = ("unknown", "not_ready", "candidate", "ready")

# Schema 1.2.0 reserved literals -- exported so downstream code can
# pattern-match against the surface-extractor's outputs without typos.
PLACEMENT_SURFACE_ROLES = (
    "primary_sketch_surface",   # face Sage may sketch on
    "reference_surface",        # face Sage may dimension to / locate against
    "do_not_edit",              # face the operator has marked off-limits
)
PLACEMENT_SURFACE_TYPES = (
    "planar",
    "cylindrical",
    "curved",
    "unknown",
)
PLACEMENT_CAPABILITIES = (
    "sketch_on_face",
    "extruded_boss",
    "extruded_cut",
    "hole_wizard_pattern",
    "reference_only",            # MVP default for every region
)

_AXIS_LABELS = ("x", "y", "z")


# ---------------------------------------------------------------------------
# Path helpers
# ---------------------------------------------------------------------------

def semantic_regions_path(library_dir: Path, pn: str, revision: str) -> Path:
    """Canonical location: parts/{pn}/{rev}/{pn}_semantic_regions.json."""
    return library_dir / "parts" / pn / revision / SEMANTIC_REGIONS_FILENAME.format(pn=pn)


def _glb_path(library_dir: Path, pn: str, revision: str) -> Path:
    return library_dir / "parts" / pn / revision / f"{pn}_colored.glb"


def _feature_colors_path(library_dir: Path, pn: str, revision: str) -> Path:
    return library_dir / "parts" / pn / revision / f"{pn}_feature_colors.json"


def _part_json_path(library_dir: Path, pn: str, revision: str) -> Path:
    return library_dir / "parts" / pn / revision / f"{pn}.json"


def _intake_manifest_path(library_dir: Path, pn: str, revision: str) -> Path:
    return library_dir / "parts" / pn / revision / "intake_manifest.json"


# ---------------------------------------------------------------------------
# sourceFeatures lookup -- maps GLB node names back to their raw
# SolidWorks feature names via the feature_colors.json sidecar.
# ---------------------------------------------------------------------------

def _load_node_to_source_feature(library_dir: Path, pn: str, revision: str) -> Dict[str, Dict[str, str]]:
    """Return glb_node_name -> {sw_name, cad_feature_id} lookup.

    SolidWorksExtractor writes {pn}_feature_colors.json with snake_case
    keys:
        {"partNumber": ...,
         "features": [
           {"cad_feature_id": "netblend_boundary_surface3",
            "sw_name":        "Boundary-Surface3",
            "type":           "netblend",
            "display_label":  "Boundary-Surface3",
            "color":          "#...",
            "glb_node_name":  "netblend_boundary_surface3"}, ...]}

    This loader keys on `glb_node_name` because that is the field the
    extractor pins as the bridge between rendered geometry and CAD
    metadata. For 1030034 it happens to equal `cad_feature_id`, but
    that equivalence is a coincidence of the current GenerateFeatureId
    implementation -- future schemas may diverge them.

    Also accepts camelCase keys (cadFeatureId / swName / glbNodeName /
    glbNode) as a defensive fallback in case a downstream writer
    emits a stylised variant.

    Returns {} when the sidecar is missing or unparseable -- the
    builder still produces a valid output, just with sourceFeatures
    empty for every region."""
    fcp = _feature_colors_path(library_dir, pn, revision)
    if not fcp.exists():
        return {}
    try:
        doc = json.loads(fcp.read_text(encoding="utf-8-sig"))
    except Exception:
        return {}
    out: Dict[str, Dict[str, str]] = {}
    feats = doc.get("features") if isinstance(doc, dict) else None
    if not isinstance(feats, list):
        return out
    for f in feats:
        if not isinstance(f, dict):
            continue
        # glb_node_name is the explicit pointer to the GLB node; if
        # absent (older sidecar versions did not write it) we fall
        # back to cad_feature_id, which equals the node name under
        # current GenerateFeatureId rules.
        glb_node = (f.get("glb_node_name")
                    or f.get("glbNodeName")
                    or f.get("glbNode")
                    or f.get("cad_feature_id")
                    or f.get("cadFeatureId"))
        sw_name = (f.get("sw_name")
                   or f.get("swName")
                   or f.get("name"))
        cad_id  = (f.get("cad_feature_id")
                   or f.get("cadFeatureId")
                   or f.get("id"))
        if not (isinstance(glb_node, str) and glb_node.strip()):
            continue
        # sw_name is the most useful field for a human operator; if
        # missing fall back to display_label or cad_feature_id so the
        # caller always has SOMETHING to surface.
        if not (isinstance(sw_name, str) and sw_name.strip()):
            sw_name = (f.get("display_label") or cad_id or "")
        out[glb_node.strip()] = {
            "sw_name":        (sw_name or "").strip(),
            "cad_feature_id": (cad_id or "").strip(),
        }
    return out


# ---------------------------------------------------------------------------
# Preservation of operator-reviewed regions
# ---------------------------------------------------------------------------

def _load_existing(out_path: Path) -> Optional[Dict[str, Any]]:
    if not out_path.exists():
        return None
    try:
        doc = json.loads(out_path.read_text(encoding="utf-8-sig"))
    except Exception:
        return None
    return doc if isinstance(doc, dict) else None


def _extract_reviewed_regions(existing: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Pull regions where reviewed==true from the prior file. These
    are operator-curated and must be preserved across re-draft.

    Regions loaded from a pre-1.1.0 file are upgraded in place so the
    final document is schema-consistent (the new visualTargets /
    cadTargets / editableParameters / editReadiness / requiresReview
    fields are added if absent without disturbing curator content).
    Existing values for those fields are kept -- the curator may have
    already populated CAD-target metadata by the time the next draft
    runs."""
    if not existing:
        return []
    regions = existing.get("regions")
    if not isinstance(regions, list):
        return []
    out = []
    for r in regions:
        if isinstance(r, dict) and r.get("reviewed") is True:
            # Defensive copy so caller modifications don't bleed back.
            upgraded = json.loads(json.dumps(r))
            _upgrade_region_to_current(upgraded)
            out.append(upgraded)
    return out


def _upgrade_region_to_1_1_0(region: Dict[str, Any]) -> None:
    """Schema 1.0.0 -> 1.1.0: seed CAD-edit orchestration placeholders.
    Idempotent -- existing values pass through untouched via setdefault."""
    region.setdefault("requiresReview", True)
    region.setdefault("editReadiness", "not_ready")
    glb_nodes = list(region.get("glbNodes") or [])
    src_feats = list(region.get("sourceFeatures") or [])
    vt = region.setdefault("visualTargets", {})
    vt.setdefault("glbNodes", glb_nodes)
    ct = region.setdefault("cadTargets", {})
    ct.setdefault("sourceFeatures",   src_feats)
    ct.setdefault("upstreamFeatures", [])
    ct.setdefault("sketches",         [])
    ct.setdefault("planes",           [])
    ct.setdefault("dimensions",       [])
    region.setdefault("editableParameters", [])


def _upgrade_region_to_1_2_0(region: Dict[str, Any]) -> None:
    """Schema 1.1.0 -> 1.2.0: seed CAD-edit PLANNING placeholders
    (placementSurfaces, placementCapabilities). Idempotent."""
    region.setdefault("placementSurfaces", [])
    region.setdefault("placementCapabilities", ["reference_only"])


def _upgrade_region_to_1_3_0(region: Dict[str, Any]) -> None:
    """Schema 1.2.0 -> 1.3.0: seed CAD-side traceability fields
    (cadTargets.cadFeatureIds, unmappedGlbNodes). Idempotent.

    Does NOT auto-populate cadFeatureIds from existing glbNodes --
    that mapping is only known when the feature_colors sidecar is
    present, which is the build-time path's job. Preserved-curator
    regions get an empty list and the curator can fill it in."""
    ct = region.setdefault("cadTargets", {})
    ct.setdefault("cadFeatureIds", [])
    region.setdefault("unmappedGlbNodes", [])


def _upgrade_region_to_current(region: Dict[str, Any]) -> None:
    """Apply every schema upgrade in order. Each step is idempotent
    and only seeds missing fields, so a region already at the latest
    schema passes through unmodified."""
    _upgrade_region_to_1_1_0(region)
    _upgrade_region_to_1_2_0(region)
    _upgrade_region_to_1_3_0(region)


def _node_names_locked_by_reviewed(reviewed: List[Dict[str, Any]]) -> set:
    """Every glbNode name appearing in a reviewed region is excluded
    from the heuristic input set so the rules don't double-assign it."""
    locked = set()
    for r in reviewed:
        for n in (r.get("glbNodes") or []):
            if isinstance(n, str) and n:
                locked.add(n)
    return locked


# ---------------------------------------------------------------------------
# Region assembly
# ---------------------------------------------------------------------------

def _classify_nodes(
    nodes: List[GlbNode],
    frame: AxisFrame,
    locked: set,
) -> Tuple[Dict[str, List[GlbNode]], Dict[str, str]]:
    """Run Stage 1 (aircraft rules) then Stage 2 (name fallback) on
    every unlocked node. Returns (groups, confidence_by_region_id)."""
    groups: Dict[str, List[GlbNode]] = defaultdict(list)
    confidence_by_region: Dict[str, str] = {}

    for n in nodes:
        if n.name in locked:
            continue
        verdict = classify_node_aircraft(n, frame)
        if verdict is not None:
            region_id, conf = verdict
            groups[region_id].append(n)
            # Highest confidence among contributing nodes wins.
            confidence_by_region[region_id] = _max_confidence(
                confidence_by_region.get(region_id), conf)
            continue
        # Stage 2: fallback name bucket.
        bucket = fallback_bucket_id(n.name)
        groups[bucket].append(n)
        confidence_by_region.setdefault(bucket, "low")

    return groups, confidence_by_region


_CONFIDENCE_RANK = {"low": 0, "medium": 1, "high": 2}


def _max_confidence(a: Optional[str], b: str) -> str:
    if a is None:
        return b
    return a if _CONFIDENCE_RANK.get(a, 0) >= _CONFIDENCE_RANK.get(b, 0) else b


def _build_region(
    region_id: str,
    glb_nodes: List[GlbNode],
    confidence: str,
    node_to_source: Dict[str, Dict[str, str]],
) -> Dict[str, Any]:
    label, aliases = LABELS.get(region_id) or fallback_bucket_label(region_id)
    glb_node_names = [n.name for n in glb_nodes]

    # Walk the region's GLB nodes once, looking each up in the
    # feature_colors map. Build three parallel outputs:
    #   - source_features (sw_name list, deduped, first-occurrence
    #     order)  -- the operator-recognised SW labels
    #   - cad_feature_ids (deduped, first-occurrence) -- the stable
    #     SolidWorks API identifiers the future Sage CAD bridge
    #     consumes
    #   - unmapped_glb_nodes -- nodes that did NOT resolve through
    #     the sidecar; reported as a separate field so the curator
    #     can decide whether to drop them or supply manual mappings
    source_features: List[str] = []
    cad_feature_ids: List[str] = []
    unmapped_glb_nodes: List[str] = []
    _seen_sw, _seen_cid = set(), set()
    for nm in glb_node_names:
        entry = node_to_source.get(nm)
        if not entry:
            unmapped_glb_nodes.append(nm)
            continue
        sw = entry.get("sw_name") or ""
        cid = entry.get("cad_feature_id") or ""
        if sw and sw not in _seen_sw:
            source_features.append(sw)
            _seen_sw.add(sw)
        if cid and cid not in _seen_cid:
            cad_feature_ids.append(cid)
            _seen_cid.add(cid)
        # An entry present but with both fields empty still counts
        # as mapped (the sidecar acknowledged the node) -- no
        # unmapped_glb_nodes entry. This is intentional.

    # Per-region note that owns up to the uncertainty.
    if region_id == "uncategorized":
        notes = ("No spatial rule matched and the node names did not "
                 "share a feature-type prefix. Operator should reassign.")
    elif region_id == "fuselage_candidate":
        notes = ("Heuristic flagged this as possibly fuselage based on "
                 "a long length-axis span or a construction-feature "
                 "name (split-line / ruled surface). Operator must "
                 "confirm before relying on this label.")
    elif region_id.startswith("features_"):
        notes = ("Name-based fallback bucket -- nodes share a feature-"
                 "type prefix but no spatial rule placed them. Operator "
                 "should split into semantic regions.")
    else:
        notes = "AI-proposed grouping; operator should verify."
    # Tack on a review pointer when some GLB nodes did not resolve
    # through the feature_colors sidecar. The structured field
    # unmappedGlbNodes carries the data; the note carries the
    # operator-facing hint.
    if unmapped_glb_nodes:
        notes = (notes + " " +
                 f"Review: {len(unmapped_glb_nodes)} GLB node(s) lacked a "
                 "feature_colors mapping; see unmappedGlbNodes.")

    # Forward-compat: the schema is the bridge to future SOLIDWORKS
    # Sage CAD-edit orchestration. visualTargets / cadTargets /
    # editableParameters / editReadiness / requiresReview are the
    # placeholders the dependency extractor + parameter extractor
    # will fill in.
    return {
        "regionId":       region_id,
        "label":          label,
        "aliases":        list(aliases),
        # Original MVP top-level fields (kept for the schema 1.0.0
        # contract; structurally mirrored under visualTargets /
        # cadTargets for the 1.1.0+ readers).
        "glbNodes":       glb_node_names,
        "sourceFeatures": source_features,
        "confidence":     confidence,
        "reviewed":       False,
        # CAD-edit orchestration scaffolding (schema 1.1.0+) --------
        "requiresReview": True,
        "editReadiness":  "not_ready",
        "visualTargets":  {
            "glbNodes": list(glb_node_names),
        },
        "cadTargets":     {
            # sourceFeatures mirrors the top-level field; cadFeatureIds
            # carries the stable SolidWorks identifiers the future
            # Sage bridge consumes. Both populated from
            # feature_colors.json (schema 1.3.0+).
            "sourceFeatures":   list(source_features),
            "cadFeatureIds":    list(cad_feature_ids),
            "upstreamFeatures": [],
            "sketches":         [],
            "planes":           [],
            "dimensions":       [],
        },
        "editableParameters": [],
        # Schema 1.2.0 -- future CAD-edit PLANNING scaffolding ------
        "placementSurfaces":     [],
        "placementCapabilities": ["reference_only"],
        # Schema 1.3.0 -- traceability gap reporting ---------------
        "unmappedGlbNodes":  list(unmapped_glb_nodes),
        # -----------------------------------------------------------
        "source":         _DEFAULT_REGION_SOURCE,
        "notes":          notes,
    }


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_draft_regions(library_dir: Path, pn: str, revision: str) -> Dict[str, Any]:
    """Build the draft semantic-regions document and return it.

    Does NOT write to disk -- callers (server endpoint, tests) decide
    when to persist via _write_semantic_regions. Reads:
      - parts/{pn}/{rev}/{pn}_colored.glb           (required)
      - parts/{pn}/{rev}/{pn}_feature_colors.json   (optional -- enables sourceFeatures)
      - parts/{pn}/{rev}/intake_manifest.json       (optional -- noted in axisFrame metadata)
      - any prior {pn}_semantic_regions.json        (preserves reviewed=true regions)

    Raises FileNotFoundError when the GLB is absent (the only hard
    dependency)."""
    glb = _glb_path(library_dir, pn, revision)
    summary = inspect_glb(glb)
    frame = detect_axis_frame(summary)
    node_to_source = _load_node_to_source_feature(library_dir, pn, revision)

    out_path = semantic_regions_path(library_dir, pn, revision)
    existing = _load_existing(out_path)
    reviewed_regions = _extract_reviewed_regions(existing)
    locked_node_names = _node_names_locked_by_reviewed(reviewed_regions)

    groups, confidence_by_region = _classify_nodes(summary.nodes, frame, locked_node_names)

    regions: List[Dict[str, Any]] = []
    # Preserved reviewed regions come first (deterministic order).
    for r in reviewed_regions:
        regions.append(r)
    # Then heuristic groups, in a stable id order.
    for region_id in sorted(groups.keys()):
        conf = confidence_by_region.get(region_id, "low")
        regions.append(_build_region(region_id, groups[region_id], conf, node_to_source))

    summary_block = {
        "totalNodes":     len(summary.nodes),
        "regionCount":    len(regions),
        "reviewedCount":  sum(1 for r in regions if r.get("reviewed") is True),
        "lockedNodes":    sorted(locked_node_names),
    }

    axis_block = {
        "lengthAxis":    _AXIS_LABELS[frame.length_axis],
        "lateralAxis":   _AXIS_LABELS[frame.lateral_axis],
        "verticalAxis":  _AXIS_LABELS[frame.vertical_axis],
        "lengthRange":   round(frame.length_range, 6),
        "lateralRange":  round(frame.lateral_range, 6),
        "verticalRange": round(frame.vertical_range, 6),
        "overallMin":    list(summary.overall_min),
        "overallMax":    list(summary.overall_max),
    }

    return {
        "schemaVersion":   SCHEMA_VERSION,
        "partNumber":      pn,
        "revision":        revision,
        "generatedAtUtc":  _dt.datetime.now(_dt.timezone.utc).isoformat(timespec="seconds"),
        "generator":       summary.generator,
        "axisFrame":       axis_block,
        "summary":         summary_block,
        "regions":         regions,
    }


def write_semantic_regions(library_dir: Path, pn: str, revision: str, doc: Dict[str, Any]) -> Path:
    """Persist the draft to disk. Atomic write (tmp + replace)."""
    out_path = semantic_regions_path(library_dir, pn, revision)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    payload = json.dumps(doc, indent=2)
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(out_path)
    return out_path
