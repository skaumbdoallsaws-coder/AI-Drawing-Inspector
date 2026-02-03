"""Validation schema rules for matcher-native callout types.

Defines required fields and value constraints per callout type.
Used by the validator to check parsed callouts before matching.
"""

from typing import Dict, List, Set


# Required fields per callout type (field must exist and be non-empty)
REQUIRED_FIELDS: Dict[str, List[str]] = {
    "Hole": ["diameter"],
    "TappedHole": ["threadSize"],
    "CounterboreHole": ["cboreDiameter"],
    "CountersinkHole": ["csinkDiameter"],
    "Fillet": ["radius"],
    "Chamfer": ["size"],
    "Thread": ["threadSize"],
    "GDT": ["gdtType"],
    "SurfaceFinish": ["roughness"],
    "Dimension": ["nominal"],
    "Tolerance": [],       # Just needs raw text
    "Slot": [],
    "Bend": [],
    "Note": [],
    "Unknown": [],         # Unknown always passes (already flagged)
}

# Valid callout types
VALID_CALLOUT_TYPES: Set[str] = set(REQUIRED_FIELDS.keys())

# Numeric fields that must be positive if present
POSITIVE_NUMERIC_FIELDS: Set[str] = {
    "diameter", "radius", "size", "depth",
    "cboreDiameter", "cboreDepth", "csinkDiameter",
    "nominal", "roughness", "toleranceValue",
}

# Angle fields that must be in range [0, 360]
ANGLE_FIELDS: Set[str] = {"csinkAngle", "angle"}

# Quantity fields that must be positive integers
QUANTITY_FIELDS: Set[str] = {"quantity"}


def get_required_fields(callout_type: str) -> List[str]:
    """Get required fields for a callout type."""
    return REQUIRED_FIELDS.get(callout_type, [])


def is_valid_callout_type(callout_type: str) -> bool:
    """Check if a callout type is recognized."""
    return callout_type in VALID_CALLOUT_TYPES
