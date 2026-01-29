"""
Base Analyzer Module

Shared functionality for all drawing type analyzers.
Includes part identity resolution, title block parsing, and common extraction logic.
"""

import os
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from ..utils.pdf_render import PageArtifact
    from ..utils.sw_library import SwJsonLibrary, SwPartEntry
    from ..classifier.drawing_classifier import ClassificationResult


@dataclass
class ResolvedPartIdentity:
    """Result of part identity resolution."""
    partNumber: str
    confidence: float  # 0.0 to 1.0
    source: str  # "filename+sw", "pdf_text+sw", "fallback"
    swJsonPath: Optional[str] = None
    candidates_tried: List[str] = field(default_factory=list)

    @property
    def has_sw_data(self) -> bool:
        """Whether SolidWorks data was found for this part."""
        return self.swJsonPath is not None


@dataclass
class AnalysisResult:
    """Container for drawing analysis results."""
    identity: ResolvedPartIdentity
    classification: Optional['ClassificationResult'] = None
    features: List[Dict[str, Any]] = field(default_factory=list)
    quality_audit: Dict[str, Any] = field(default_factory=dict)
    bom_data: Dict[str, Any] = field(default_factory=dict)
    manufacturing_notes: Dict[str, Any] = field(default_factory=dict)
    ocr_callouts: List[Dict[str, Any]] = field(default_factory=list)
    sw_requirements: List[Dict[str, Any]] = field(default_factory=list)
    mate_requirements: List[Dict[str, Any]] = field(default_factory=list)
    comparison: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            'identity': {
                'partNumber': self.identity.partNumber,
                'confidence': self.identity.confidence,
                'source': self.identity.source,
                'hasSWData': self.identity.has_sw_data,
            },
            'features': self.features,
            'qualityAudit': self.quality_audit,
            'bomData': self.bom_data,
            'manufacturingNotes': self.manufacturing_notes,
            'ocrCallouts': self.ocr_callouts,
            'swRequirements': self.sw_requirements,
            'mateRequirements': self.mate_requirements,
            'comparison': self.comparison,
        }


# ============================================================================
# Part Identity Resolution
# ============================================================================

def clean_filename(filename: str) -> str:
    """Remove known suffixes like Paint, REV, etc."""
    cleaned = re.sub(r'[\s_]*(Paint|PAINT)$', '', filename, flags=re.IGNORECASE)
    return cleaned.strip()


def extract_pn_candidates(text: str) -> List[str]:
    """
    Extract potential part number candidates from filename or text.

    Handles patterns like:
    - 1013572_01
    - 101357201-03
    - 314884W_0
    - 046-935-REV-A

    Returns list of candidates (most specific to least).
    """
    name_no_ext = os.path.splitext(text)[0]
    # Remove duplicate markers like (1), (2)
    name_no_ext = re.sub(r'\s*\(\d+\)$', '', name_no_ext)
    cleaned = clean_filename(name_no_ext)
    parts = re.split(r'[\s_]+', cleaned)

    if not parts:
        return []

    base = parts[0]
    candidates = []

    # 1. Base as-is
    candidates.append(base)

    # 2. Without hyphens
    base_no_hyphen = base.replace('-', '')
    if base_no_hyphen != base:
        candidates.append(base_no_hyphen)

    # 3. Remove letter suffixes (046-935A -> 046-935)
    if base and base[-1].isalpha() and len(base) > 1:
        candidates.append(base[:-1])
        candidates.append(base[:-1].replace('-', ''))

    # 4. Handle revision pattern (046-935-01 -> 046-935)
    rev_match = re.match(r'^(.+)-(\d{1,2})$', base)
    if rev_match:
        main_part = rev_match.group(1)
        candidates.append(main_part)
        candidates.append(main_part.replace('-', ''))

    # 5. Handle REV suffix (046-935-REV-A -> 046-935)
    rev_alpha = re.match(r'^(.+?)[-_]?REV[-_]?[A-Z0-9]*$', base, re.IGNORECASE)
    if rev_alpha:
        candidates.append(rev_alpha.group(1))
        candidates.append(rev_alpha.group(1).replace('-', ''))

    # 6. Peeling - progressively remove trailing digits
    temp = base_no_hyphen
    while len(temp) > 5:
        temp = temp[:-1]
        candidates.append(temp)

    # Remove duplicates, preserve order
    seen = set()
    unique = []
    for c in candidates:
        if c and c not in seen:
            seen.add(c)
            unique.append(c)

    return unique


def resolve_part_identity(
    pdf_path: str,
    artifacts: List['PageArtifact'],
    sw_lib: 'SwJsonLibrary'
) -> ResolvedPartIdentity:
    """
    Resolve part identity using robust filename matching.

    Tries multiple strategies:
    1. Extract candidates from PDF filename
    2. Try each candidate against SW library
    3. Try PDF embedded text if available
    4. Fall back to filename stem

    Args:
        pdf_path: Path to the PDF file
        artifacts: Rendered page artifacts (for embedded text)
        sw_lib: SolidWorks JSON library for lookup

    Returns:
        ResolvedPartIdentity with match details
    """
    filename = os.path.basename(pdf_path)
    candidates = extract_pn_candidates(filename)

    # Try each candidate against SW library
    for candidate in candidates:
        entry = sw_lib.lookup(candidate)
        if entry:
            return ResolvedPartIdentity(
                partNumber=entry.part_number or candidate,
                confidence=1.0,
                source="filename+sw",
                swJsonPath=entry.json_path,
                candidates_tried=candidates
            )

    # Try PDF embedded text
    for art in artifacts:
        if art.direct_text:
            text_candidates = extract_pn_candidates(art.direct_text[:200])
            for candidate in text_candidates[:5]:
                entry = sw_lib.lookup(candidate)
                if entry:
                    return ResolvedPartIdentity(
                        partNumber=entry.part_number or candidate,
                        confidence=0.8,
                        source="pdf_text+sw",
                        swJsonPath=entry.json_path,
                        candidates_tried=candidates + text_candidates[:5]
                    )

    # Fallback - use first candidate or filename stem
    fallback_pn = candidates[0] if candidates else Path(pdf_path).stem
    return ResolvedPartIdentity(
        partNumber=fallback_pn,
        confidence=0.3,
        source="fallback",
        swJsonPath=None,
        candidates_tried=candidates
    )


# ============================================================================
# Base Analyzer Class
# ============================================================================

class BaseAnalyzer(ABC):
    """
    Abstract base class for drawing type analyzers.

    Each drawing type (machined part, sheet metal, weldment, etc.)
    has a specialized analyzer that inherits from this base class.
    """

    # Override in subclasses
    drawing_type: str = "unknown"
    use_ocr: bool = True
    use_qwen: bool = True

    def __init__(self):
        self.result: Optional[AnalysisResult] = None

    @abstractmethod
    def analyze(
        self,
        artifacts: List['PageArtifact'],
        identity: ResolvedPartIdentity,
        sw_entry: Optional['SwPartEntry'] = None,
    ) -> AnalysisResult:
        """
        Analyze drawing pages and return results.

        Args:
            artifacts: Rendered page images
            identity: Resolved part identity
            sw_entry: SolidWorks part data if available

        Returns:
            AnalysisResult with extracted features and comparison
        """
        pass

    def extract_title_block(self, qwen_result: Dict[str, Any]) -> Dict[str, Any]:
        """
        Extract title block information from Qwen analysis.

        Args:
            qwen_result: Result from Qwen feature extraction

        Returns:
            Title block data
        """
        title_info = qwen_result.get('titleBlockInfo', {})
        quality = qwen_result.get('titleBlockCompleteness', {})

        return {
            'partNumber': title_info.get('partNumber') or quality.get('partNumberValue'),
            'revision': title_info.get('revision') or quality.get('revisionValue'),
            'scale': title_info.get('scale') or quality.get('scaleValue'),
            'material': qwen_result.get('material') or quality.get('materialValue'),
            'description': quality.get('descriptionValue'),
            'date': quality.get('dateValue'),
            'drawnBy': quality.get('drawnByValue'),
        }

    def merge_evidence(
        self,
        ocr_callouts: List[Dict],
        qwen_features: List[Dict]
    ) -> List[Dict]:
        """
        Merge OCR callouts and Qwen features with deduplication.

        Args:
            ocr_callouts: Callouts parsed from OCR text
            qwen_features: Features extracted by Qwen VLM

        Returns:
            Merged and deduplicated feature list
        """
        merged = []
        seen_callouts = set()

        # Add OCR callouts first (more precise text)
        for callout in ocr_callouts:
            raw = callout.get('raw', '')
            if raw and raw not in seen_callouts:
                seen_callouts.add(raw)
                merged.append(callout)

        # Add Qwen features that don't duplicate OCR
        for feature in qwen_features:
            callout_text = feature.get('callout', '')
            if callout_text and callout_text not in seen_callouts:
                # Convert Qwen format to standard format
                converted = self._convert_qwen_feature(feature)
                if converted:
                    seen_callouts.add(callout_text)
                    merged.append(converted)

        return merged

    def _convert_qwen_feature(self, feature: Dict) -> Optional[Dict]:
        """Convert a Qwen feature to standard callout format."""
        ftype = feature.get('type', '').lower()
        callout = feature.get('callout', '')

        if 'tapped' in ftype or 'thread' in ftype:
            return {
                'calloutType': 'TappedHole',
                'raw': callout,
                'source': 'qwen',
                'description': feature.get('description'),
                'quantity': feature.get('quantity', 1),
            }
        elif 'through' in ftype and 'hole' in ftype:
            return {
                'calloutType': 'Hole',
                'isThrough': True,
                'raw': callout,
                'source': 'qwen',
                'description': feature.get('description'),
                'quantity': feature.get('quantity', 1),
            }
        elif 'blind' in ftype and 'hole' in ftype:
            return {
                'calloutType': 'Hole',
                'isThrough': False,
                'raw': callout,
                'source': 'qwen',
                'description': feature.get('description'),
                'quantity': feature.get('quantity', 1),
            }
        elif 'counterbore' in ftype:
            return {
                'calloutType': 'Counterbore',
                'raw': callout,
                'source': 'qwen',
            }
        elif 'countersink' in ftype:
            return {
                'calloutType': 'Countersink',
                'raw': callout,
                'source': 'qwen',
            }
        elif 'fillet' in ftype:
            return {
                'calloutType': 'Fillet',
                'raw': callout,
                'source': 'qwen',
            }
        elif 'chamfer' in ftype:
            return {
                'calloutType': 'Chamfer',
                'raw': callout,
                'source': 'qwen',
            }
        elif 'slot' in ftype:
            return {
                'calloutType': 'Slot',
                'raw': callout,
                'source': 'qwen',
            }

        return None

    def filter_sheet_metal_holes(self, hole_groups: List[Dict]) -> List[Dict]:
        """
        Filter out bogus holes from sheet metal bend geometry.

        Sheet metal CAD exports often include holes where:
        - reconciliationNote contains "Bend"
        - depth > 10x diameter (artifact of bend calculation)

        Args:
            hole_groups: Hole groups from SW JSON

        Returns:
            Filtered hole groups
        """
        filtered = []
        for group in hole_groups:
            note = group.get('reconciliationNote', '')
            diameter = group.get('diameterInches', 0)
            depth = group.get('depthInches', 0)

            # Skip bend artifacts
            if 'bend' in note.lower():
                continue

            # Skip suspicious depth/diameter ratio
            if diameter > 0 and depth > 10 * diameter:
                continue

            filtered.append(group)

        return filtered
