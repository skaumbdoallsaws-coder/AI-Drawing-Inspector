"""Parse Qwen VLM output into structured callouts."""

import re
from typing import List, Dict


# Map Qwen feature types to canonical callout types
FEATURE_TYPE_MAP = {
    "TappedHole": "TappedHole",
    "ThroughHole": "Hole",
    "BlindHole": "Hole",
    "Counterbore": "Hole",
    "Countersink": "Hole",
    "Fillet": "Fillet",
    "Chamfer": "Chamfer",
    "Thread": "TappedHole",
    "Slot": "Slot",
}

# Keywords indicating general notes, not features
NOTE_KEYWORDS = ["REMOVE ALL BURRS", "BREAK SHARP EDGES", "DEBURR", "CLEAN"]

# Common surface finish Ra values (microinches) - should not be parsed as features
SURFACE_FINISH_VALUES = {"4", "8", "16", "32", "63", "125", "250", "500"}


def parse_qwen_features(qwen_data: Dict) -> List[Dict]:
    """
    Convert Qwen feature analysis to callout format.

    Includes post-processing validation to fix common VLM misclassifications:
    - R.XX patterns are always fillets, not holes
    - Linear dimensions without diameter symbols are skipped
    - General notes are filtered out

    Args:
        qwen_data: Qwen feature analysis output (from DrawingAnalyzer)

    Returns:
        List of callout dicts with type, dimensions, and source
    """
    if "parse_error" in qwen_data:
        return []

    callouts = []

    for feat in qwen_data.get("features", []):
        ftype = feat.get("type", "")
        callout = feat.get("callout", "")
        callout_upper = callout.upper().strip()

        # POST-PROCESSING: Fix common misclassifications

        # R.XX patterns are ALWAYS fillets/radii, not holes
        if re.match(r"^R\.?\d", callout_upper) or re.match(r"^R\s*\.?\d", callout_upper):
            ftype = "Fillet"

        # Skip linear dimensions misidentified as holes
        if ftype in ["ThroughHole", "BlindHole", "Counterbore", "Countersink"]:
            has_dia_symbol = "Ø" in callout or "\u2205" in callout or "DIA" in callout_upper
            has_slot_indicator = "SLOT" in callout_upper or "X" in callout_upper
            # If no diameter symbol and looks like bare number, skip
            if not has_dia_symbol and not has_slot_indicator:
                if re.match(r"^\d*\.?\d+$", callout.strip()):
                    continue

        # Skip general notes misclassified as features
        if any(kw in callout_upper for kw in NOTE_KEYWORDS):
            continue

        # Skip surface finish values misidentified as features (e.g., "63" or "63°")
        # Surface finish is typically shown as Ra value: 4, 8, 16, 32, 63, 125, 250, 500
        callout_digits = re.sub(r"[°\s]", "", callout).strip()
        if callout_digits in SURFACE_FINISH_VALUES:
            continue

        # Skip standalone angle callouts that aren't chamfers (e.g., "63°", "45°")
        # These are often surface finish or projection angle indicators
        if re.match(r"^\d+°?$", callout.strip()):
            continue

        callout_type = FEATURE_TYPE_MAP.get(ftype, ftype)

        entry = {
            "calloutType": callout_type,
            "description": feat.get("description", ""),
            "location": feat.get("location", ""),
            "quantity": feat.get("quantity", 1),
            "raw": callout,
            "source": "qwen",
        }

        # Parse dimensions from callout text
        _extract_dimensions(entry, callout, callout_type)

        callouts.append(entry)

    return callouts


def _extract_dimensions(entry: Dict, callout: str, callout_type: str) -> None:
    """
    Extract thread/hole dimensions from callout text.

    Updates entry dict in-place with extracted dimensions.

    Args:
        entry: Callout dict to update
        callout: Raw callout text
        callout_type: Canonical callout type
    """
    # Metric threads: M6x1.0, M10X1.5
    thread_match = re.search(r"M(\d+(?:\.\d+)?)[xX](\d+(?:\.\d+)?)", callout)
    if thread_match:
        entry["thread"] = {
            "standard": "Metric",
            "nominalDiameterMm": float(thread_match.group(1)),
            "pitch": float(thread_match.group(2)),
        }

    # Hole diameters - keep in inches
    if callout_type == "Hole":
        # Match diameter with various symbols
        hole_match = re.search(r"[oO\u00d8\u2205\u03c6\u2300]?\s*(\.?\d+\.?\d*)", callout)
        if hole_match:
            try:
                val = float(hole_match.group(1))
                if val > 0:
                    entry["diameterInches"] = val
                    entry["isThrough"] = "THRU" in callout.upper()
            except ValueError:
                pass

    # Fillet radius
    if callout_type == "Fillet":
        fillet_match = re.search(r"R\s*(\.?\d+\.?\d*)", callout, re.IGNORECASE)
        if fillet_match:
            try:
                entry["radiusInches"] = float(fillet_match.group(1))
            except ValueError:
                pass

    # Chamfer distance
    if callout_type == "Chamfer":
        chamfer_match = re.search(r"(\.?\d+\.?\d*)\s*[xX]\s*45", callout)
        if chamfer_match:
            try:
                entry["distance1Inches"] = float(chamfer_match.group(1))
                entry["angleDegrees"] = 45
            except ValueError:
                pass
