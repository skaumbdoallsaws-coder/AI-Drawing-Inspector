"""Drawing-mode classification: tells the rest of the app which workflow to use.

Different drawing types need different downstream treatment. Standard inspected
part drawings drive dimension/feature/FAI workflows; assembly drawings driven
by a BOM table drive BOM-aware compare and part-isolation workflows. This
module encodes that distinction in a small, auditable contract that the
backend, the agent context, and the frontend can all consume.

Contract
--------
``classify_drawing_mode(...)`` returns a dict with these keys:

- ``drawing_type``           one of ``feature_inspection`` | ``assembly_bom`` | ``unknown``
- ``workflow_mode``          one of ``dimension_feature_review`` | ``bom_compare`` | ``unknown``
- ``drawing_capabilities``   bool map (see ``_capabilities_for``)
- ``classification_reasons`` list of short string codes documenting why
  the classifier chose the type. Always populated; tells callers (and the
  agent) what evidence was actually used.

Inputs
------
The caller passes whatever signals it can cheaply derive. Missing signals are
not guessed; instead, ``has_bom_table`` and ``has_dimension_annotations``
fall back to inspecting the supplied ``drawing_map`` if one is available.

Why this lives in its own module
--------------------------------
The backend, the agent context-builder, and any future tool dispatcher all
need to agree on the same vocabulary. Putting the rules in one place keeps
the contract honest and makes the inference auditable per-call via
``classification_reasons``.
"""

from typing import Dict, List, Optional


# Public string constants — exported so callers can compare without
# hard-coding magic strings at the use site.
DRAWING_TYPE_FEATURE_INSPECTION = "feature_inspection"
DRAWING_TYPE_ASSEMBLY_BOM = "assembly_bom"
DRAWING_TYPE_UNKNOWN = "unknown"

WORKFLOW_DIMENSION_FEATURE_REVIEW = "dimension_feature_review"
WORKFLOW_BOM_COMPARE = "bom_compare"
WORKFLOW_UNKNOWN = "unknown"

# tableType strings that the SolidWorks drawing extractor uses for BOMs.
# Lowercased before comparison.
_BOM_TABLE_TYPE_TOKENS = ("bom",)


# ---------------------------------------------------------------------------
# Drawing-map signal helpers
# ---------------------------------------------------------------------------

def _has_bom_table_in_drawing_map(drawing_map: Optional[dict]) -> bool:
    """Return True when at least one sheet has a ``tableType`` matching ``bom``.

    This is the strongest single signal for classifying a drawing as
    assembly_bom: the SolidWorks drawing extractor explicitly tags BOM tables.
    """
    if not drawing_map or not isinstance(drawing_map, dict):
        return False
    for sheet in drawing_map.get("sheets", []) or []:
        for table in sheet.get("tables", []) or []:
            ttype = (table.get("tableType") or "").strip().lower()
            if ttype in _BOM_TABLE_TYPE_TOKENS:
                return True
    return False


def _has_dimension_annotations(drawing_map: Optional[dict]) -> bool:
    """Return True when at least one view contains a displayDimension annotation."""
    if not drawing_map or not isinstance(drawing_map, dict):
        return False
    for sheet in drawing_map.get("sheets", []) or []:
        for view in sheet.get("views", []) or []:
            for ann in view.get("annotations", []) or []:
                if (ann.get("annotationType") or "").lower() == "displaydimension":
                    return True
    return False


def _looks_like_assembly_pn(part_number: Optional[str]) -> bool:
    """Soft heuristic: 6000-series part numbers are reserved for assemblies.

    Used only to keep an assembly part number from accidentally classifying
    as feature_inspection via drawing-map-presence alone. This is a hint,
    not authority — the explicit ``has_assembly_context`` signal still drives
    the call.
    """
    pn = (part_number or "").strip()
    return pn.startswith("6000") and len(pn) >= 7


# ---------------------------------------------------------------------------
# Capability matrix
# ---------------------------------------------------------------------------

def _capabilities_for(drawing_type: str) -> Dict[str, bool]:
    """Default capability flags per drawing type. Conservative for unknown.

    These tell downstream UI / agent steering which workflows are appropriate.
    The agent should prefer capabilities marked True and de-prioritise
    workflows that depend on capabilities marked False.
    """
    if drawing_type == DRAWING_TYPE_ASSEMBLY_BOM:
        return {
            "bom_compare": True,
            "dimension_overlay": False,
            "feature_overlay": False,
            "part_isolation": True,
            "assembly_compare": True,
            "fai_mode": False,
        }
    if drawing_type == DRAWING_TYPE_FEATURE_INSPECTION:
        return {
            "bom_compare": False,
            "dimension_overlay": True,
            "feature_overlay": True,
            "part_isolation": False,
            "assembly_compare": False,
            "fai_mode": True,
        }
    # Unknown — keep everything off so the agent doesn't recommend a
    # workflow without confidence.
    return {
        "bom_compare": False,
        "dimension_overlay": False,
        "feature_overlay": False,
        "part_isolation": False,
        "assembly_compare": False,
        "fai_mode": False,
    }


def _bundle(drawing_type: str, workflow_mode: str, reasons: List[str]) -> dict:
    """Pack the three required output sections into the public contract."""
    return {
        "drawing_type": drawing_type,
        "workflow_mode": workflow_mode,
        "drawing_capabilities": _capabilities_for(drawing_type),
        "classification_reasons": reasons,
    }


# ---------------------------------------------------------------------------
# Public classifier
# ---------------------------------------------------------------------------

def classify_drawing_mode(
    part_number: Optional[str] = None,
    *,
    drawing_map: Optional[dict] = None,
    has_assembly_context: bool = False,
    has_drawing_revisions: bool = False,
    has_inspection_profile: bool = False,
    has_bom_table: Optional[bool] = None,
    has_dimension_annotations: Optional[bool] = None,
) -> dict:
    """Classify a drawing into a (drawing_type, workflow_mode, capabilities) bundle.

    Args:
        part_number: the canonical part number, when known. Used only as a
            tiebreaker (assembly-PN heuristic) — never as authority.
        drawing_map: parsed ``*_drawing_map.json`` if available. Used to
            derive ``has_bom_table`` / ``has_dimension_annotations`` when
            the caller did not pass them explicitly.
        has_assembly_context: True when ``part_number`` is itself an
            assembly's number (e.g. registered in ``assembly_profiles`` on
            the server). This is NOT the same as "this part is referenced
            by some assembly" — only the top-level assembly number qualifies.
        has_drawing_revisions: True when the part has multiple revision
            folders available. Reinforces assembly_bom only when paired with
            ``has_assembly_context``.
        has_inspection_profile: True when an inspection profile exists for
            this part number.
        has_bom_table: explicit override; if None, derived from drawing_map.
        has_dimension_annotations: explicit override; if None, derived
            from drawing_map.

    Returns:
        Dict matching the module-level Contract section.
    """
    # ── Resolve drawing-map-derived signals when the caller didn't pass them ──
    if has_bom_table is None:
        has_bom_table = _has_bom_table_in_drawing_map(drawing_map)
    if has_dimension_annotations is None:
        has_dimension_annotations = _has_dimension_annotations(drawing_map)

    # ── Rule A: assembly_bom ──
    # ``assembly_bom`` is a BOM-DRIVEN workflow type: the drawing carries a
    # parts list and the agent should drive BOM-row highlighting, revision
    # compare, and part isolation. Without a BOM table on the drawing we
    # cannot honestly call the workflow ``bom_compare`` — a general-
    # arrangement assembly drawing is still an assembly but its workflow
    # is not BOM-driven, so it falls through to a different bucket.
    #
    # Therefore: ``has_bom_table`` is REQUIRED. ``has_assembly_context`` and
    # ``has_drawing_revisions`` only add corroborating reasons; they cannot
    # trip the rule on their own. This keeps the classifier from forcing
    # GA assemblies into bom_compare just because they have revisions.
    if has_bom_table:
        a_reasons: List[str] = ["bom_table_detected"]
        if has_assembly_context:
            a_reasons.append("assembly_context_present")
        if has_drawing_revisions and has_assembly_context:
            a_reasons.append("drawing_revisions_available")
        return _bundle(DRAWING_TYPE_ASSEMBLY_BOM, WORKFLOW_BOM_COMPARE, a_reasons)

    # ── Rule B: feature_inspection ──
    # Driven by part-inspection signals: explicit profile, dimension
    # annotations, or simply a drawing map present without a BOM (and
    # not an assembly-range part number).
    b_score = 0
    b_reasons: List[str] = []
    if has_inspection_profile:
        b_score += 2
        b_reasons.append("inspection_profile_present")
    if has_dimension_annotations:
        b_score += 1
        b_reasons.append("dimension_annotations_present")
    if drawing_map and not has_bom_table and not _looks_like_assembly_pn(part_number):
        b_score += 1
        b_reasons.append("drawing_map_present_no_bom")

    if b_score >= 1:
        return _bundle(
            DRAWING_TYPE_FEATURE_INSPECTION,
            WORKFLOW_DIMENSION_FEATURE_REVIEW,
            b_reasons,
        )

    # ── Rule C: unknown ──
    return _bundle(DRAWING_TYPE_UNKNOWN, WORKFLOW_UNKNOWN, ["no_classification_signals"])
