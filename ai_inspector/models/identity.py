"""Part identity resolution model."""

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class ResolvedPartIdentity:
    """
    Result of resolving a drawing's part identity.

    Created by extractors/identity.py which matches PDF filenames
    and embedded text against the SolidWorks JSON library.

    Attributes:
        part_number: The resolved part number
        confidence: Match confidence (0.0-1.0)
            - 1.0: Exact match found in SW library
            - 0.8: Match via PDF embedded text
            - 0.3: Fallback to filename (no SW match)
        source: How the match was made
            - "filename+sw": Filename matched SW library
            - "pdf_text+sw": PDF text matched SW library
            - "fallback": No match, using filename as part number
        sw_json_path: Path to matching SolidWorks JSON (None if no match)
        candidates_tried: List of part number candidates that were tried
    """

    part_number: str
    confidence: float
    source: str
    sw_json_path: Optional[str] = None
    candidates_tried: List[str] = field(default_factory=list)
