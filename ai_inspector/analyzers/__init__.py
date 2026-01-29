"""Type-specific drawing analyzers."""

from .base import (
    BaseAnalyzer,
    AnalysisResult,
    ResolvedPartIdentity,
    resolve_part_identity,
    extract_pn_candidates,
    clean_filename,
)

from .machined_part import MachinedPartAnalyzer, MachinedPartAnalyzerLazy


# Placeholder analyzers for types not yet implemented
# These inherit from BaseAnalyzer and use MachinedPartAnalyzer behavior
class SheetMetalAnalyzer(MachinedPartAnalyzer):
    """Analyzer for sheet metal parts (bends, flat patterns)."""
    drawing_type = "sheet_metal"
    use_ocr = True
    use_qwen = True


class WeldmentAnalyzer(MachinedPartAnalyzer):
    """Analyzer for weldments (weld symbols, BOM)."""
    drawing_type = "weldment"
    use_ocr = False  # Weldments are mostly visual
    use_qwen = True


class AssemblyAnalyzer(MachinedPartAnalyzer):
    """Analyzer for assemblies (BOM, balloons)."""
    drawing_type = "assembly"
    use_ocr = False  # Assemblies are mostly visual
    use_qwen = True


class CastingAnalyzer(MachinedPartAnalyzer):
    """Analyzer for castings (critical dims, reference dims)."""
    drawing_type = "casting"
    use_ocr = True
    use_qwen = True


class PurchasedPartAnalyzer(MachinedPartAnalyzer):
    """Analyzer for purchased parts (manufacturer table)."""
    drawing_type = "purchased_part"
    use_ocr = False  # Reference only
    use_qwen = True


class GearAnalyzer(MachinedPartAnalyzer):
    """Analyzer for gears (gear data table)."""
    drawing_type = "gear"
    use_ocr = True
    use_qwen = True


__all__ = [
    # Base classes
    "BaseAnalyzer",
    "AnalysisResult",
    "ResolvedPartIdentity",
    "resolve_part_identity",
    "extract_pn_candidates",
    "clean_filename",
    # Type-specific analyzers
    "MachinedPartAnalyzer",
    "MachinedPartAnalyzerLazy",
    "SheetMetalAnalyzer",
    "WeldmentAnalyzer",
    "AssemblyAnalyzer",
    "CastingAnalyzer",
    "PurchasedPartAnalyzer",
    "GearAnalyzer",
]
