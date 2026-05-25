"""Read-side helpers consumed by Sage's compare-answer rendering.

Pure: no LLM, no network. The compare-answer code path calls these
to produce physical-language sentences when a feature intent map
is present, and falls back to its current technical wording when
the map is absent or the lookup misses.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, Optional

from .builder import feature_intent_map_path, load_feature_intent_map


def lookup_feature_intent(
    library_dir: Path,
    pn:          str,
    revision:    str,
    cad_feature_id: str,
) -> Optional[Dict[str, Any]]:
    """Return the per-feature entry from the intent map, or None
    when the map is absent / malformed / does not contain the
    feature. The map is loaded fresh per call -- the file is small
    and Sage's compare-answer path is operator-driven, so the cost
    is negligible and there is no cache-coherence risk vs disk
    re-drafts."""
    if not cad_feature_id:
        return None
    doc = load_feature_intent_map(library_dir, pn, revision)
    if doc is None:
        return None
    feats = doc.get("features")
    if not isinstance(feats, list):
        return None
    for entry in feats:
        if isinstance(entry, dict) and entry.get("cadFeatureId") == cad_feature_id:
            return entry
    return None


# Param-name aliases. The diff payload uses the SolidWorks param
# name (e.g. "depth1_mm"); the intent map's control may use the same
# or a slightly different canonical form. We match on a small alias
# table so a rule author can list one canonical key and still match
# the diff's variants. Matched entirely on lowercase.
_PARAM_ALIASES = {
    "depth1_mm":   {"depth1_mm", "depth_mm", "extrudedepth_mm", "depth"},
    "thickness_mm": {"thickness_mm", "wallthickness_mm", "thickness"},
    "diameter_mm": {"diameter_mm", "diameter"},
    "angle_deg":   {"angle_deg", "revolveangle_deg", "angle"},
    "radius_mm":   {"radius_mm", "filletradius_mm", "radius"},
    "distance_mm": {"distance_mm", "chamferdistance_mm", "distance"},
}


def _param_matches(control_param: str, diff_param: str) -> bool:
    """Loose equality across the alias table. control_param is the
    rule-author's canonical key; diff_param is whatever the part
    diff payload emitted."""
    if not control_param or not diff_param:
        return False
    a = control_param.strip().lower()
    b = diff_param.strip().lower()
    if a == b:
        return True
    for canon, aliases in _PARAM_ALIASES.items():
        if a == canon and b in aliases:
            return True
        if b == canon and a in aliases:
            return True
        if a in aliases and b in aliases:
            return True
    return False


def intent_entry_physical_phrase_for_param(
    entry:      Dict[str, Any],
    param_name: str,
    old_value:  Any,
    new_value:  Any,
) -> Optional[str]:
    """Render a physical-language sentence for a parameter change on
    THIS feature, e.g. "The propeller blade thickness increased from
    0.5 mm to 5.5 mm." Returns None when:
      - the entry has no matching control for param_name, OR
      - the entry has no physicalName / displayName, OR
      - the old/new values aren't numeric (we fall back to technical
        wording rather than emit a malformed sentence).
    """
    if not isinstance(entry, dict):
        return None
    controls = entry.get("controls") or []
    if not isinstance(controls, list):
        return None
    control: Optional[Dict[str, Any]] = None
    for c in controls:
        if not isinstance(c, dict):
            continue
        if _param_matches(str(c.get("parameter") or ""), str(param_name or "")):
            control = c
            break
    if control is None:
        return None

    display_name = str(control.get("displayName") or "").strip()
    units        = str(control.get("units") or "").strip() or "mm"
    if not display_name:
        return None

    # Capitalised owner phrase: "The propeller blade thickness" or
    # "The blade thickness" when no region label is available.
    region_label = str(entry.get("regionLabel") or "").strip()
    phrase_owner = region_label.lower() if region_label else ""
    # Avoid double-naming: if displayName already includes the region
    # word ("blade thickness" + region "Propeller blade"), don't
    # repeat it.
    if phrase_owner and (phrase_owner in display_name.lower()
                          or display_name.lower().startswith(phrase_owner)):
        phrase = f"The {display_name}"
    elif phrase_owner:
        phrase = f"The {phrase_owner} {display_name}"
    else:
        phrase = f"The {display_name}"

    # Direction + numeric rendering. We only build the "from X to Y"
    # tail when both values cast to float cleanly; otherwise return
    # None so the technical fallback runs.
    try:
        old_f = float(old_value)
        new_f = float(new_value)
    except (TypeError, ValueError):
        return None

    direction = "increased" if new_f > old_f \
        else ("decreased" if new_f < old_f else "stayed at")
    if direction == "stayed at":
        return f"{phrase} stayed at {old_f:g} {units}."
    return f"{phrase} {direction} from {old_f:g} {units} to {new_f:g} {units}."
