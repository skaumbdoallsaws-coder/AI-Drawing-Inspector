"""Parse structured callouts from OCR text."""

import re
from typing import List, Dict

from .patterns import PATTERNS
from ..config import default_config


def preprocess_ocr_text(ocr_lines: List[str]) -> List[str]:
    """
    Clean LightOnOCR-2 markdown/LaTeX output for regex parsing.

    Handles:
    - LaTeX diameter symbols (\\oslash, \\phi)
    - Markdown headers and formatting
    - Bullet points

    Args:
        ocr_lines: Raw OCR output lines

    Returns:
        Cleaned lines ready for regex parsing
    """
    cleaned = []

    for line in ocr_lines:
        t = line.strip()

        # Skip image references and code blocks
        if t.startswith("![") or t.startswith("```") or not t:
            continue

        # Convert LaTeX diameter symbols to unicode
        t = t.replace("$\\oslash$", "\u2205")
        t = t.replace("$\\emptyset$", "\u2205")
        t = t.replace("$\\phi$", "\u03c6")
        t = t.replace("$\\times$", "x")
        t = t.replace("$\\pm$", "\u00b1")
        t = t.replace("$\\degree$", "\u00b0")
        t = re.sub(r"\$\\[Oo]slash\$", "\u2205", t)

        # Strip markdown formatting
        t = re.sub(r"^#{1,6}\s*", "", t)  # Headers
        t = re.sub(r"\*{1,3}([^*]+)\*{1,3}", r"\1", t)  # Bold/italic
        t = t.lstrip("- ")  # Bullet points
        t = t.strip()

        if t:
            cleaned.append(t)

    return cleaned


def parse_ocr_callouts(ocr_lines: List[str]) -> List[Dict]:
    """
    Extract callouts from OCR text using regex patterns.

    Extracts:
    - Metric threads (M6x1.0)
    - Imperial threads (1/2-13)
    - Through holes, blind holes
    - Counterbore, countersink
    - Fillets, chamfers

    All hole diameters stored in inches (as-is from drawing).

    Args:
        ocr_lines: Raw OCR output lines

    Returns:
        List of callout dicts with type, dimensions, and source
    """
    callouts = []
    seen_raws = set()  # Deduplicate

    # Preprocess OCR text
    cleaned_lines = preprocess_ocr_text(ocr_lines)
    raw_text = "\n".join(cleaned_lines)

    # --- Metric threads (M6x1.0) ---
    for match in re.finditer(PATTERNS["metric_thread"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "TappedHole",
            "thread": {
                "standard": "Metric",
                "nominalDiameterMm": float(match.group(1)),
                "pitch": float(match.group(2)),
            },
            "raw": raw,
            "source": "ocr",
        })

    # --- Imperial threads (1/2-13) ---
    for match in re.finditer(PATTERNS["imperial_thread"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "TappedHole",
            "thread": {
                "standard": "Imperial",
                "fraction": match.group(1),
                "tpi": int(match.group(2)),
            },
            "raw": raw,
            "source": "ocr",
        })

    # --- Through holes ---
    for match in re.finditer(PATTERNS["thru_hole"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        val = float(match.group(1))
        # Skip unreasonable values
        if val > default_config.max_hole_diameter_inches:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "Hole",
            "diameterInches": val,
            "isThrough": True,
            "raw": raw,
            "source": "ocr",
        })

    # --- Blind holes ---
    for match in re.finditer(PATTERNS["blind_hole"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        val = float(match.group(1))
        # Skip unreasonable values
        if val > default_config.max_hole_diameter_inches:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "Hole",
            "diameterInches": val,
            "depthInches": float(match.group(2)),
            "isThrough": False,
            "raw": raw,
            "source": "ocr",
        })

    # --- Counterbore ---
    for match in re.finditer(PATTERNS["counterbore"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "Hole",
            "diameterInches": float(match.group(1)),
            "isCounterbore": True,
            "raw": raw,
            "source": "ocr",
        })

    # --- Countersink ---
    for match in re.finditer(PATTERNS["countersink"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "Hole",
            "diameterInches": float(match.group(1)),
            "isCountersink": True,
            "raw": raw,
            "source": "ocr",
        })

    # --- Major/Minor diameter (casting drawings) ---
    for match in re.finditer(PATTERNS["major_minor_dia"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        val = float(match.group(1))
        tol_val = float(match.group(2)) if match.group(2) else None
        callouts.append({
            "calloutType": "Hole",
            "diameterInches": val,
            "diameterMaxInches": tol_val,
            "isThrough": None,
            "raw": raw,
            "source": "ocr",
        })

    # --- Standalone diameter (no THRU/DEEP qualifier) ---
    for match in re.finditer(PATTERNS["diameter"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        val = float(match.group(1))
        # Skip values outside reasonable range (likely OCR noise/garbage)
        if val < default_config.min_hole_diameter_inches:
            continue
        if val > default_config.max_hole_diameter_inches:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "Hole",
            "diameterInches": val,
            "isThrough": None,
            "raw": raw,
            "source": "ocr",
        })

    # --- Fillets: R.125 ---
    for match in re.finditer(PATTERNS["fillet"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        val = float(match.group(1))
        # Skip values outside reasonable range
        if val < 0.001:
            continue
        if val > default_config.max_fillet_radius_inches:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "Fillet",
            "radiusInches": val,
            "raw": raw,
            "source": "ocr",
        })

    # --- Chamfers: .030 x 45° ---
    for match in re.finditer(PATTERNS["chamfer"], raw_text, re.IGNORECASE):
        raw = match.group(0)
        if raw in seen_raws:
            continue
        seen_raws.add(raw)
        callouts.append({
            "calloutType": "Chamfer",
            "distance1Inches": float(match.group(1)),
            "angleDegrees": 45,
            "raw": raw,
            "source": "ocr",
        })

    return callouts
