"""Deterministic name/type rules that translate a CAD feature into a
physical-language intent entry.

Pure heuristics, no LLM. Each rule returns a partial entry that the
builder folds into the per-feature schema. Rules are intentionally
narrow -- when no rule fires, the builder emits a generic entry
with featureRole='unknown', editRole='reference', and an empty
controls[] so the operator can curate it.

The classifier signature is:
    classify(sw_name, sw_type, cad_feature_id, region_label) -> dict

`region_label` carries the human-friendly region name (e.g.
"Propeller", "Top wing") which gates the wording for Boss-Extrude
depth: a propeller boss says "blade thickness", a wing boss says
"wing thickness", an arbitrary boss falls back to "body length".
"""

from __future__ import annotations

from typing import Any, Dict, Optional


# Edit-role enum. Mirrors the cad-edit-handoff contract's editTargets/
# propagationFeatures/referenceFeatures classification.
EDIT_ROLES = ("primary_edit_target", "propagation", "reference", "unknown")


# Region-label keyword -> physical-thickness-noun. The keyword search is
# case-insensitive substring; first hit wins.
_REGION_THICKNESS_NOUNS = (
    ("propeller",      "blade thickness"),
    ("blade",          "blade thickness"),
    ("wing",           "wing thickness"),
    ("stabilizer",     "stabilizer thickness"),
    ("strut",          "strut thickness"),
    ("rudder",         "rudder thickness"),
    ("fuselage",       "body length"),
    ("hull",           "body length"),
)


def _region_thickness_noun(region_label: Optional[str]) -> str:
    """Pick the most user-friendly thickness noun based on the region
    label. Falls back to "body length" when no keyword matches because
    Boss-Extrude on an unknown region is ambiguous between thickness
    (sheet metal-ish) and length (rib/spar-ish); length is the
    less-wrong default."""
    label = (region_label or "").lower()
    for keyword, noun in _REGION_THICKNESS_NOUNS:
        if keyword in label:
            return noun
    return "body length"


def _name_or_type_matches(sw_name: str, sw_type: str, cad_id: str, *needles: str) -> bool:
    blob = " ".join([sw_name or "", sw_type or "", cad_id or ""]).lower()
    return any(n.lower() in blob for n in needles)


def classify(
    sw_name:        Optional[str],
    sw_type:        Optional[str],
    cad_feature_id: Optional[str],
    region_label:   Optional[str],
) -> Dict[str, Any]:
    """Return a partial intent entry: {physicalName, featureRole,
    editRole, controls[]}. Missing fields mean "let the builder use
    its defaults"."""
    nm  = (sw_name or "").strip()
    tp  = (sw_type or "").strip()
    cid = (cad_feature_id or "").strip()

    # ── Pattern / mirror -- propagation, not edit ─────────────────
    # Match early so "MirrorBoss" doesn't fall into the Boss rule.
    if _name_or_type_matches(nm, tp, cid,
                              "cirpattern", "linpattern", "mirrorsolid",
                              "mirrorrefsurf", "mirrorpattern",
                              "tablepattern", "curvedpattern",
                              "sketchpattern", "fillpattern"):
        return {
            "physicalName": _region_thickness_noun_replacement(nm, region_label, "instance copies"),
            "featureRole":  "propagates the source feature to additional instances",
            "editRole":     "propagation",
            "controls":     [],
        }
    # Defensive: bare "mirror" / "pattern" in the name.
    if "mirror" in nm.lower() or "pattern" in nm.lower():
        return {
            "physicalName": "instance copies",
            "featureRole":  "propagates the source feature to additional instances",
            "editRole":     "propagation",
            "controls":     [],
        }

    # ── Shell ─────────────────────────────────────────────────────
    if _name_or_type_matches(nm, tp, cid, "shell"):
        return {
            "physicalName": "hollowed wall",
            "featureRole":  "hollows the solid leaving a uniform-thickness wall",
            "editRole":     "primary_edit_target",
            "controls": [
                {
                    "parameter":       "thickness_mm",
                    "displayName":     "wall thickness",
                    "units":           "mm",
                    "physicalMeaning": "Increasing this thickens the remaining wall after the shell operation.",
                },
            ],
        }

    # ── Cut-Extrude (slot / hole / pocket) ────────────────────────
    if _name_or_type_matches(nm, tp, cid, "cut-extrude", "ice_cut_extrude", "cutextrude"):
        return {
            "physicalName": "cut pocket",
            "featureRole":  "removes material along the extrusion direction",
            "editRole":     "primary_edit_target",
            "controls": [
                {
                    "parameter":       "depth1_mm",
                    "displayName":     "cut depth",
                    "units":           "mm",
                    "physicalMeaning": "Increasing this makes the cut/slot/hole reach further into the part.",
                },
            ],
        }

    # ── Hole Wizard ───────────────────────────────────────────────
    if _name_or_type_matches(nm, tp, cid, "holewzd", "holewizard"):
        return {
            "physicalName": "hole",
            "featureRole":  "drilled hole feature",
            "editRole":     "primary_edit_target",
            "controls": [
                {
                    "parameter":       "diameter_mm",
                    "displayName":     "hole diameter",
                    "units":           "mm",
                    "physicalMeaning": "Increasing this widens the hole.",
                },
                {
                    "parameter":       "depth1_mm",
                    "displayName":     "hole depth",
                    "units":           "mm",
                    "physicalMeaning": "Increasing this makes the hole reach further into the part.",
                },
            ],
        }

    # ── Revolve (solid revolve, NOT surface revolve which is reference) ─
    if _name_or_type_matches(nm, tp, cid, "revolution_revolve", "revolve") \
            and not _name_or_type_matches(nm, tp, cid, "revolvrefsurf", "refsurf"):
        return {
            "physicalName": "revolved body",
            "featureRole":  "creates a body of revolution",
            "editRole":     "primary_edit_target",
            "controls": [
                {
                    "parameter":       "diameter_mm",
                    "displayName":     "revolve diameter",
                    "units":           "mm",
                    "physicalMeaning": "Increasing this widens the revolved profile.",
                },
                {
                    "parameter":       "angle_deg",
                    "displayName":     "revolve angle",
                    "units":           "deg",
                    "physicalMeaning": "Increasing this sweeps the profile through a larger arc.",
                },
            ],
        }

    # ── Boss-Extrude ──────────────────────────────────────────────
    # Order matters: this comes AFTER cut/hole/revolve/shell so the
    # narrower rules win when both could match.
    if _name_or_type_matches(nm, tp, cid,
                              "boss-extrude", "iceextrude", "ice_boss_extrude",
                              "boss", "extrude"):
        noun = _region_thickness_noun(region_label)
        return {
            "physicalName": f"{(region_label or '').strip().lower() or 'body'} extrude" if not (region_label or "").strip()
                            else f"{(region_label or '').strip().lower()} extrude",
            "featureRole":  f"creates the {region_label.strip().lower() if region_label else 'body'} body",
            "editRole":     "primary_edit_target",
            "controls": [
                {
                    "parameter":       "depth1_mm",
                    "displayName":     noun,
                    "units":           "mm",
                    "physicalMeaning": (
                        f"Increasing this makes the {noun} larger along the extrusion direction."
                    ),
                },
            ],
        }

    # ── Surfaces / reference planes / sketches -- reference only ──
    if _name_or_type_matches(nm, tp, cid,
                              "planarsurface", "extrurefsurface", "revolvrefsurf",
                              "ruledsrffromedge", "netblend", "boundarysurface",
                              "refplane", "refaxis", "refpoint", "refcoord",
                              "sketch", "compcurve"):
        return {
            "physicalName": "construction surface or reference",
            "featureRole":  "construction geometry; does not produce material",
            "editRole":     "reference",
            "controls":     [],
        }

    # ── Fillets / chamfers -- editable but rarely the demo target ─
    if _name_or_type_matches(nm, tp, cid, "fillet"):
        return {
            "physicalName": "edge fillet",
            "featureRole":  "rounds an edge",
            "editRole":     "primary_edit_target",
            "controls": [
                {
                    "parameter":       "radius_mm",
                    "displayName":     "fillet radius",
                    "units":           "mm",
                    "physicalMeaning": "Increasing this makes the rounded edge larger.",
                },
            ],
        }
    if _name_or_type_matches(nm, tp, cid, "chamfer"):
        return {
            "physicalName": "chamfered edge",
            "featureRole":  "bevels an edge",
            "editRole":     "primary_edit_target",
            "controls": [
                {
                    "parameter":       "distance_mm",
                    "displayName":     "chamfer width",
                    "units":           "mm",
                    "physicalMeaning": "Increasing this makes the bevel wider.",
                },
            ],
        }

    # ── Fallback: unknown ─────────────────────────────────────────
    return {
        "physicalName": "",
        "featureRole":  "",
        "editRole":     "unknown",
        "controls":     [],
    }


def _region_thickness_noun_replacement(name: str, region_label: Optional[str], fallback: str) -> str:
    """For pattern/mirror features, the physical name reads more
    naturally as 'mirrored <region thickness noun>' when we know
    the region. Falls back to a generic word."""
    base = _region_thickness_noun(region_label)
    if base in ("body length",):
        return fallback
    if (region_label or "").strip():
        return f"propagated {region_label.strip().lower()} instances"
    return fallback
