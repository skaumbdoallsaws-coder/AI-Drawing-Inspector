"""
Drawing Type Classifier

Identifies the type of engineering drawing from extracted text and/or image.
This determines which analyzer to use and whether OCR is needed.

Drawing Types:
- MACHINED_PART: Turned/milled parts with holes, threads, tolerances
- SHEET_METAL: Bent parts with flat patterns, bend callouts
- WELDMENT: Welded assemblies with weld symbols, BOM
- ASSEMBLY: Non-welded assemblies with BOM, balloon callouts
- CASTING: Cast parts (ductile iron) with reference dimensions
- PURCHASED_PART: Bearings, fasteners with manufacturer cross-reference
- GEAR: Gears with gear data tables
"""

import re
from enum import Enum
from dataclasses import dataclass, field
from typing import List, Optional


class DrawingType(Enum):
    """Supported drawing types."""
    MACHINED_PART = "machined_part"
    SHEET_METAL = "sheet_metal"
    WELDMENT = "weldment"
    ASSEMBLY = "assembly"
    CASTING = "casting"
    PURCHASED_PART = "purchased_part"
    GEAR = "gear"
    UNKNOWN = "unknown"


@dataclass
class TypeConfig:
    """Configuration for each drawing type."""
    use_ocr: bool
    use_qwen: bool
    features_to_extract: List[str]
    features_to_skip: List[str]
    critical_checks: List[str]


# Type-specific configurations
TYPE_CONFIGS = {
    DrawingType.MACHINED_PART: TypeConfig(
        use_ocr=True,
        use_qwen=True,
        features_to_extract=['holes', 'threads', 'chamfers', 'tolerances', 'gdt', 'surface_finish'],
        features_to_skip=['weld_symbols', 'bom', 'bend_callouts'],
        critical_checks=['thread_callouts', 'hole_dimensions', 'tolerances']
    ),
    DrawingType.SHEET_METAL: TypeConfig(
        use_ocr=True,
        use_qwen=True,
        features_to_extract=['holes', 'slots', 'bends', 'flat_pattern', 'material_gauge'],
        features_to_skip=['weld_symbols', 'threads', 'gdt'],
        critical_checks=['bend_callouts', 'flat_pattern_dims', 'hole_dimensions']
    ),
    DrawingType.WELDMENT: TypeConfig(
        use_ocr=False,  # Weldments have few dimensions, mostly visual
        use_qwen=True,
        features_to_extract=['weld_symbols', 'bom', 'weld_callouts', 'assembly_notes'],
        features_to_skip=['threads', 'tolerances', 'gdt'],
        critical_checks=['weld_symbols_present', 'bom_complete', 'weld_sizes']
    ),
    DrawingType.ASSEMBLY: TypeConfig(
        use_ocr=False,  # Assemblies are mostly visual
        use_qwen=True,
        features_to_extract=['bom', 'balloon_callouts', 'assembly_notes'],
        features_to_skip=['threads', 'tolerances', 'gdt', 'weld_symbols'],
        critical_checks=['bom_complete', 'balloons_match_bom']
    ),
    DrawingType.CASTING: TypeConfig(
        use_ocr=True,
        use_qwen=True,
        features_to_extract=['holes', 'threads', 'critical_dims'],
        features_to_skip=['weld_symbols', 'bend_callouts'],
        critical_checks=['critical_features_dimensioned', 'reference_dims_marked']
    ),
    DrawingType.PURCHASED_PART: TypeConfig(
        use_ocr=False,  # Reference only
        use_qwen=True,
        features_to_extract=['manufacturer_table', 'part_numbers'],
        features_to_skip=['threads', 'tolerances', 'gdt', 'holes'],
        critical_checks=['manufacturer_cross_reference']
    ),
    DrawingType.GEAR: TypeConfig(
        use_ocr=True,
        use_qwen=True,
        features_to_extract=['gear_data', 'teeth', 'pitch', 'pressure_angle', 'tolerances'],
        features_to_skip=['weld_symbols', 'bom'],
        critical_checks=['gear_data_complete', 'pitch_diameter']
    ),
}


@dataclass
class ClassificationResult:
    """Result of drawing type classification."""
    drawing_type: DrawingType
    confidence: float
    signals: List[str] = field(default_factory=list)
    config: Optional[TypeConfig] = None

    def __post_init__(self):
        if self.config is None and self.drawing_type in TYPE_CONFIGS:
            self.config = TYPE_CONFIGS[self.drawing_type]

    @property
    def use_ocr(self) -> bool:
        """Whether OCR should be used for this drawing type."""
        return self.config.use_ocr if self.config else True

    @property
    def use_qwen(self) -> bool:
        """Whether Qwen VLM should be used for this drawing type."""
        return self.config.use_qwen if self.config else True


def classify_drawing(text: str, image=None) -> ClassificationResult:
    """
    Classify a drawing based on extracted text (and optionally image).

    Args:
        text: Text extracted from the PDF (via PyMuPDF get_text())
        image: Optional rendered image (for future visual classification)

    Returns:
        ClassificationResult with type, confidence, and signals
    """
    t = text.upper()

    # Remove tolerance block false positives
    # "CASTINGS = ±.030/FT" is a tolerance spec, not part type
    t_clean = re.sub(r'CASTINGS\s*=\s*[^\n]+', '', t)

    signals = []

    # === WELDMENT (highest priority - explicit keyword) ===
    if 'WELDT' in t_clean or 'WELDMENT' in t_clean:
        signals.append("'WELDT' or 'WELDMENT' in title/text")
        # Check for BOM (weldments usually have them)
        if _has_bom(t_clean):
            signals.append("BOM table detected")
        return ClassificationResult(
            drawing_type=DrawingType.WELDMENT,
            confidence=0.95,
            signals=signals
        )

    # === ASSEMBLY with BOM (explicit BOM structure) ===
    if _has_bom(t_clean):
        signals.append("BOM table detected (ITEM NO + QTY columns)")
        if 'ASSY' in t_clean or 'ASSEM' in t_clean or 'SUBASSEM' in t_clean:
            signals.append("'ASSY' or 'ASSEM' in title")
        return ClassificationResult(
            drawing_type=DrawingType.ASSEMBLY,
            confidence=0.90,
            signals=signals
        )

    # === PURCHASED PART (manufacturer cross-reference) ===
    if _is_purchased_part(t_clean):
        signals.append("Manufacturer cross-reference table detected")
        if 'ALL DIMENSIONS FOR REFERENCE ONLY' in t_clean:
            signals.append("'ALL DIMENSIONS FOR REFERENCE ONLY' note")
        return ClassificationResult(
            drawing_type=DrawingType.PURCHASED_PART,
            confidence=0.95,
            signals=signals
        )

    # === GEAR (gear data table) ===
    if _is_gear(t_clean):
        signals.append("Gear data table detected")
        return ClassificationResult(
            drawing_type=DrawingType.GEAR,
            confidence=0.90,
            signals=signals
        )

    # === CASTING (material callout) ===
    if _is_casting(t_clean):
        signals.append("Casting material/process detected")
        return ClassificationResult(
            drawing_type=DrawingType.CASTING,
            confidence=0.85,
            signals=signals
        )

    # === SHEET METAL (flat pattern or bend callouts) ===
    if _is_sheet_metal(t_clean):
        signals.append("Sheet metal indicators detected")
        return ClassificationResult(
            drawing_type=DrawingType.SHEET_METAL,
            confidence=0.85,
            signals=signals
        )

    # === ASSEMBLY by keyword (no BOM detected) ===
    if 'ASSY' in t_clean or 'ASSEM' in t_clean or 'SUBASSEM' in t_clean:
        signals.append("'ASSY' or 'ASSEM' in title (no BOM found)")
        return ClassificationResult(
            drawing_type=DrawingType.ASSEMBLY,
            confidence=0.70,
            signals=signals
        )

    # === DEFAULT: MACHINED PART ===
    signals.append("No specific type indicators - defaulting to machined part")
    return ClassificationResult(
        drawing_type=DrawingType.MACHINED_PART,
        confidence=0.60,
        signals=signals
    )


def _has_bom(text: str) -> bool:
    """Check if text contains a BOM (Bill of Materials) table."""
    # Look for BOM column headers
    has_item_col = 'ITEM NO' in text or 'ITEM_NO' in text or 'ITEM #' in text
    has_qty_col = 'QTY' in text or 'QUANTITY' in text
    has_part_col = 'PART_NUMBER' in text or 'PART NUMBER' in text or 'PART#' in text
    has_desc_col = 'DESCRIPTION' in text

    # Need at least ITEM + QTY or PART + DESCRIPTION
    return (has_item_col and has_qty_col) or (has_part_col and has_desc_col)


def _is_purchased_part(text: str) -> bool:
    """Check if drawing is for a purchased part."""
    # Manufacturer cross-reference table
    mfg_keywords = ['MANUFACTURER:', 'MANUFACTURER', 'MFG:']
    has_mfg_table = any(kw in text for kw in mfg_keywords)

    # Multiple bearing/part suppliers
    suppliers = ['NSK', 'SKF', 'AST BEARING', 'TIMKEN', 'FAG', 'NTN']
    supplier_count = sum(1 for s in suppliers if s in text)

    # Reference only note
    ref_only = 'ALL DIMENSIONS FOR REFERENCE ONLY' in text

    return has_mfg_table or supplier_count >= 2 or ref_only


def _is_gear(text: str) -> bool:
    """Check if drawing is for a gear."""
    gear_keywords = [
        'DIAMETRAL PITCH',
        'NUMBER OF TEETH',
        'PRESSURE ANGLE',
        'PITCH DIAMETER',
        'MODULE',
        'ADDENDUM',
        'DEDENDUM',
        'WHOLE DEPTH',
        'CIRCULAR PITCH'
    ]
    # Need at least 2 gear-specific keywords
    return sum(1 for kw in gear_keywords if kw in text) >= 2


def _is_casting(text: str) -> bool:
    """Check if drawing is for a casting."""
    # Material callouts
    casting_materials = ['DUCTILE IRON', 'IRON CASTING', 'CAST IRON', 'GRAY IRON']
    has_casting_material = any(mat in text for mat in casting_materials)

    # MFG ITEM # (manufactured/cast item)
    has_mfg_item = 'MFG ITEM #' in text or 'MFG ITEM#' in text

    return has_casting_material or has_mfg_item


def _is_sheet_metal(text: str) -> bool:
    """Check if drawing is for a sheet metal part."""
    # Flat pattern view
    if 'FLAT PATTERN' in text:
        return True

    # Bend callouts: UP 90° R .03 or DOWN 90° R .03
    if re.search(r'(UP|DOWN)\s+\d+.*R\s*\.', text):
        return True

    # Material gauge (10 GA, 14 GA, etc.)
    if re.search(r'\d+\s*GA\.?\s*(MILD\s*)?STEEL', text):
        return True

    # Sheet metal description keywords with material context
    sheet_keywords = ['BRKT', 'BRACKET', 'COVER', 'PANEL', 'DOOR', 'GUARD', 'SHIELD', 'ENCLOSURE']
    steel_keywords = ['STEEL', 'MLD STL', 'MILD STEEL']

    has_sheet_part = any(kw in text for kw in sheet_keywords)
    has_steel = any(kw in text for kw in steel_keywords)

    return has_sheet_part and has_steel


def get_analyzer_for_type(drawing_type: DrawingType):
    """
    Get the appropriate analyzer class for a drawing type.

    Returns the analyzer class (not instance) to be instantiated by caller.
    """
    # Lazy import to avoid circular dependencies
    from ..analyzers import (
        MachinedPartAnalyzer,
        SheetMetalAnalyzer,
        WeldmentAnalyzer,
        AssemblyAnalyzer,
        CastingAnalyzer,
        PurchasedPartAnalyzer,
        GearAnalyzer,
    )

    analyzers = {
        DrawingType.MACHINED_PART: MachinedPartAnalyzer,
        DrawingType.SHEET_METAL: SheetMetalAnalyzer,
        DrawingType.WELDMENT: WeldmentAnalyzer,
        DrawingType.ASSEMBLY: AssemblyAnalyzer,
        DrawingType.CASTING: CastingAnalyzer,
        DrawingType.PURCHASED_PART: PurchasedPartAnalyzer,
        DrawingType.GEAR: GearAnalyzer,
    }

    return analyzers.get(drawing_type, MachinedPartAnalyzer)
