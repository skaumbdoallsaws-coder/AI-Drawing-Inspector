"""Diff result structure for drawing vs CAD comparison.

The DiffResult is the core output of the QC comparison, showing:
- What features matched (drawing callout = SW model)
- What's missing (SW model feature not on drawing)
- What's extra (drawing callout not in SW model)
- Match rate statistics
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Dict, Any, Optional

from .sw_extractor import SwFeatureExtractor, SwFeature
from .matcher import FeatureMatcher, MatchResult, MatchStatus
from ..extractors.evidence_merger import DrawingEvidence


@dataclass
class DiffEntry:
    """
    A single entry in the diff result.

    Attributes:
        category: Feature category (thread, hole, fillet, chamfer)
        status: Match status string
        drawing_value: Value from drawing (e.g., "M6x1.0")
        sw_value: Value from SolidWorks
        delta: Numeric difference (if applicable)
        notes: Explanation
    """
    category: str
    status: str
    drawing_value: str = ""
    sw_value: str = ""
    delta: Optional[float] = None
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        d = {
            "category": self.category,
            "status": self.status,
            "drawingValue": self.drawing_value,
            "swValue": self.sw_value,
            "notes": self.notes,
        }
        if self.delta is not None:
            d["delta"] = self.delta
        return d


@dataclass
class DiffResult:
    """
    Complete comparison result between drawing and SolidWorks model.

    Attributes:
        schema_version: Diff schema version
        part_number: Part number being compared
        compared_at: ISO timestamp
        has_sw_data: Whether SolidWorks data was available
        match_rate: Percentage of features that matched (0.0-1.0)
        summary: Quick summary counts
        entries: List of DiffEntry for each feature
        drawing_evidence: Reference to source drawing evidence
        sw_feature_count: Number of features in SW model
    """

    schema_version: str = "1.0.0"
    part_number: str = ""
    compared_at: str = ""
    has_sw_data: bool = False
    match_rate: float = 0.0
    summary: Dict[str, int] = field(default_factory=dict)
    entries: List[DiffEntry] = field(default_factory=list)
    drawing_evidence: Optional[Dict] = None
    sw_feature_count: int = 0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "schemaVersion": self.schema_version,
            "partNumber": self.part_number,
            "comparedAt": self.compared_at,
            "hasSwData": self.has_sw_data,
            "matchRate": self.match_rate,
            "summary": self.summary,
            "entries": [e.to_dict() for e in self.entries],
            "swFeatureCount": self.sw_feature_count,
        }

    @property
    def passed(self) -> bool:
        """Check if comparison passed (no missing critical features)."""
        return self.summary.get("missing", 0) == 0

    @property
    def matched_count(self) -> int:
        """Number of matched features."""
        return self.summary.get("matched", 0)

    @property
    def missing_count(self) -> int:
        """Number of missing features (in SW but not drawing)."""
        return self.summary.get("missing", 0)

    @property
    def extra_count(self) -> int:
        """Number of extra features (on drawing but not in SW)."""
        return self.summary.get("extra", 0)


def compare_drawing(
    evidence: DrawingEvidence,
    sw_data: Optional[Dict[str, Any]],
) -> DiffResult:
    """
    Compare drawing evidence against SolidWorks CAD data.

    This is the main comparison function that:
    1. Extracts features from SW JSON
    2. Matches drawing callouts against SW features
    3. Builds a DiffResult with match statistics

    Args:
        evidence: DrawingEvidence from extraction pipeline
        sw_data: SolidWorks JSON data (None if not available)

    Returns:
        DiffResult with comparison details

    Example:
        evidence = build_drawing_evidence(pn, ocr_lines, qwen_output)
        sw_data = sw_library.lookup(pn).data

        diff = compare_drawing(evidence, sw_data)
        print(f"Match rate: {diff.match_rate:.1%}")
        print(f"Missing: {diff.missing_count}")
    """
    result = DiffResult(
        part_number=evidence.part_number,
        compared_at=datetime.now().isoformat() + "Z",
        drawing_evidence=evidence.to_dict() if evidence else None,
    )

    # Handle no SW data case
    if not sw_data:
        result.has_sw_data = False
        result.summary = {
            "matched": 0,
            "missing": 0,
            "extra": len(evidence.found_callouts) if evidence else 0,
            "tolerance_fail": 0,
        }
        # All drawing callouts are "extra" since we can't verify them
        for callout in (evidence.found_callouts if evidence else []):
            result.entries.append(DiffEntry(
                category=callout.get("calloutType", "unknown"),
                status="unverified",
                drawing_value=callout.get("raw", str(callout)),
                notes="No SolidWorks data available for verification",
            ))
        return result

    # Extract SW features
    extractor = SwFeatureExtractor()
    sw_features = extractor.extract(sw_data)
    result.has_sw_data = True
    result.sw_feature_count = len(sw_features)

    # Get drawing callouts
    drawing_callouts = evidence.found_callouts if evidence else []

    # Run matching
    matcher = FeatureMatcher()
    match_results = matcher.match_all(drawing_callouts, sw_features)

    # Convert match results to diff entries
    counts = {"matched": 0, "missing": 0, "extra": 0, "tolerance_fail": 0}

    for mr in match_results:
        entry = _match_result_to_entry(mr)
        result.entries.append(entry)

        if mr.status == MatchStatus.MATCHED:
            counts["matched"] += 1
        elif mr.status == MatchStatus.MISSING:
            counts["missing"] += 1
        elif mr.status == MatchStatus.EXTRA:
            counts["extra"] += 1
        elif mr.status == MatchStatus.TOLERANCE_FAIL:
            counts["tolerance_fail"] += 1

    result.summary = counts

    # Calculate match rate
    total_sw = len(sw_features)
    if total_sw > 0:
        result.match_rate = counts["matched"] / total_sw
    else:
        result.match_rate = 1.0 if counts["extra"] == 0 else 0.0

    return result


def _match_result_to_entry(mr: MatchResult) -> DiffEntry:
    """Convert MatchResult to DiffEntry."""
    # Determine category
    if mr.drawing_callout:
        category = mr.drawing_callout.get("calloutType", "unknown")
    elif mr.sw_feature:
        category = mr.sw_feature.feature_type
    else:
        category = "unknown"

    # Format values
    drawing_val = ""
    sw_val = ""

    if mr.drawing_callout:
        drawing_val = mr.drawing_callout.get("raw", "")
        if not drawing_val:
            # Build from structured data
            if "thread" in mr.drawing_callout:
                t = mr.drawing_callout["thread"]
                if "nominalDiameterMm" in t:
                    drawing_val = f"M{t['nominalDiameterMm']}x{t.get('pitch', '?')}"
                elif "fraction" in t:
                    drawing_val = f"{t['fraction']}-{t.get('tpi', '?')}"
            elif "diameterInches" in mr.drawing_callout:
                drawing_val = f"{mr.drawing_callout['diameterInches']:.4f}\""
            elif "radiusInches" in mr.drawing_callout:
                drawing_val = f"R{mr.drawing_callout['radiusInches']:.3f}\""

    if mr.sw_feature:
        if mr.sw_feature.thread:
            t = mr.sw_feature.thread
            if "nominalDiameterMm" in t:
                sw_val = f"M{t['nominalDiameterMm']}x{t.get('pitch', '?')}"
            elif "raw" in t:
                sw_val = t["raw"]
        elif mr.sw_feature.diameter_inches:
            sw_val = f"{mr.sw_feature.diameter_inches:.4f}\""
        elif mr.sw_feature.radius_inches:
            sw_val = f"R{mr.sw_feature.radius_inches:.3f}\""

    return DiffEntry(
        category=category,
        status=mr.status.value,
        drawing_value=drawing_val,
        sw_value=sw_val,
        delta=mr.delta,
        notes=mr.notes,
    )
