"""SolidWorks data models."""

from dataclasses import dataclass, field
from typing import Dict, Any


@dataclass
class SwPartEntry:
    """
    A SolidWorks part from the JSON library.

    Represents a single part's data as extracted from SolidWorks
    and stored in the sw_json_library.

    Attributes:
        json_path: Full path to the JSON file
        part_number: Part number from the JSON identity section
        filename_stem: Filename without extension (for fallback matching)
        data: Complete JSON data dictionary
    """

    json_path: str
    part_number: str
    filename_stem: str = ""
    data: Dict[str, Any] = field(default_factory=dict)
