"""Merge OCR and Qwen evidence into unified DrawingEvidence."""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import List, Dict, Any, Optional

from .ocr_parser import parse_ocr_callouts
from .qwen_parser import parse_qwen_features
from ..config import default_config


@dataclass
class DrawingEvidence:
    """
    Unified drawing evidence structure.

    Combines OCR-extracted callouts with Qwen VLM analysis
    into a single evidence document for comparison.

    Attributes:
        schema_version: Evidence schema version
        part_number: Resolved part number
        extracted_at: ISO timestamp of extraction
        units: Unit system (default "inches")
        sources: Info about OCR and VLM models used
        drawing_info: Views, material, title block from Qwen
        found_callouts: Merged list of callouts from both sources
        raw_ocr_sample: First 15 lines of OCR for debugging
    """

    schema_version: str = "1.4.0"
    part_number: str = ""
    extracted_at: str = ""
    units: str = "inches"
    sources: Dict[str, Any] = field(default_factory=dict)
    drawing_info: Dict[str, Any] = field(default_factory=dict)
    found_callouts: List[Dict] = field(default_factory=list)
    raw_ocr_sample: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)


def merge_evidence(
    ocr_callouts: List[Dict],
    qwen_callouts: List[Dict],
    tolerance_inches: float = None,
) -> List[Dict]:
    """
    Merge OCR and Qwen callouts with deduplication.

    Strategy:
    - OCR preferred for precise dimensions
    - Qwen provides context (location, description)
    - Unmatched Qwen features added as 'qwen_only'

    Args:
        ocr_callouts: Callouts from OCR parser
        qwen_callouts: Callouts from Qwen parser
        tolerance_inches: Matching tolerance (default from config)

    Returns:
        Merged list of callouts with 'sources' field
    """
    if tolerance_inches is None:
        tolerance_inches = default_config.ocr_qwen_match_tolerance_inches

    merged = []
    used_qwen = set()

    for ocr in ocr_callouts:
        merged_entry = ocr.copy()
        merged_entry["sources"] = ["ocr"]

        # Find matching Qwen feature for additional context
        for qi, qwen in enumerate(qwen_callouts):
            if qi in used_qwen:
                continue
            if _callouts_match(ocr, qwen, tolerance_inches):
                merged_entry["location"] = qwen.get("location", "")
                merged_entry["description"] = qwen.get("description", "")
                merged_entry["sources"].append("qwen")
                used_qwen.add(qi)
                break

        merged.append(merged_entry)

    # Add unmatched Qwen features
    for qi, qwen in enumerate(qwen_callouts):
        if qi not in used_qwen:
            qwen_copy = qwen.copy()
            qwen_copy["sources"] = ["qwen_only"]
            merged.append(qwen_copy)

    return merged


def _callouts_match(
    ocr: Dict,
    qwen: Dict,
    tolerance_inches: float,
) -> bool:
    """
    Check if OCR and Qwen callouts refer to same feature.

    Args:
        ocr: OCR callout dict
        qwen: Qwen callout dict
        tolerance_inches: Diameter matching tolerance

    Returns:
        True if callouts match
    """
    if ocr.get("calloutType") != qwen.get("calloutType"):
        return False

    # Thread matching
    if ocr.get("thread") and qwen.get("thread"):
        nom1 = ocr["thread"].get("nominalDiameterMm", 0)
        nom2 = qwen["thread"].get("nominalDiameterMm", 0)
        return nom1 and nom2 and abs(nom1 - nom2) < 0.1

    # Hole diameter matching
    if ocr.get("diameterInches") and qwen.get("diameterInches"):
        return abs(ocr["diameterInches"] - qwen["diameterInches"]) < tolerance_inches

    return False


def build_drawing_evidence(
    part_number: str,
    ocr_lines: List[str],
    qwen_understanding: Dict,
) -> DrawingEvidence:
    """
    Build complete DrawingEvidence from OCR and Qwen outputs.

    Args:
        part_number: Resolved part number
        ocr_lines: Raw OCR output lines
        qwen_understanding: Qwen feature analysis output

    Returns:
        DrawingEvidence dataclass with all fields populated
    """
    ocr_callouts = parse_ocr_callouts(ocr_lines)
    qwen_callouts = parse_qwen_features(qwen_understanding)
    merged = merge_evidence(ocr_callouts, qwen_callouts)

    return DrawingEvidence(
        part_number=part_number,
        extracted_at=datetime.now().isoformat() + "Z",
        sources={
            "ocr": {
                "model": default_config.ocr_model_id,
                "lineCount": len(ocr_lines),
            },
            "vision": {
                "model": default_config.vlm_model_id,
                "featureCount": len(qwen_callouts),
            },
        },
        drawing_info={
            "views": qwen_understanding.get("views", []),
            "partDescription": qwen_understanding.get("partDescription", ""),
            "material": qwen_understanding.get("material", ""),
            "titleBlock": qwen_understanding.get("titleBlockInfo", {}),
            "notes": qwen_understanding.get("notes", []),
        },
        found_callouts=merged,
        raw_ocr_sample=ocr_lines[:15],
    )
