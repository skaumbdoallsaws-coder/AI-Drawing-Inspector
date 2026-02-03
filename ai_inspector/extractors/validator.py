"""Validation and repair for parsed callouts.

Rules:
- Every callout must have 'raw' (non-empty string)
- Every callout must have a valid 'calloutType'
- Required fields per type must be present and non-empty
- Numeric fields must be valid numbers
- Invalid callouts become Unknown with _invalid=True and reason

Invalid callouts are NEVER dropped -- they are preserved with error metadata
so you can debug why something failed.
"""

from typing import Any, Dict, List, Optional, Tuple

from ..schemas.callout_schema import (
    REQUIRED_FIELDS,
    VALID_CALLOUT_TYPES,
    POSITIVE_NUMERIC_FIELDS,
    ANGLE_FIELDS,
    QUANTITY_FIELDS,
    get_required_fields,
    is_valid_callout_type,
)


def validate_callout(callout: Dict[str, Any]) -> Tuple[Dict[str, Any], bool, Optional[str]]:
    """
    Validate a single parsed callout dict.

    Checks:
    1. Has 'raw' field (non-empty string)
    2. Has valid 'calloutType'
    3. Required fields are present and non-empty
    4. Numeric fields are valid
    5. Angle fields are in range
    6. Quantity fields are positive integers

    Args:
        callout: Parsed callout dict (possibly with normalized values)

    Returns:
        Tuple of (repaired_callout, is_valid, error_message)
        - If valid: (callout, True, None)
        - If invalid: (repaired_callout, False, "reason")
          repaired_callout has calloutType="Unknown", _invalid=True, _validation_error="reason"
    """
    errors: List[str] = []

    # Check 1: Must have 'raw'
    raw = callout.get("raw", "")
    if not raw or not isinstance(raw, str) or not raw.strip():
        errors.append("missing 'raw' field")

    # Check 2: Valid callout type
    callout_type = callout.get("calloutType", "")
    if not callout_type:
        errors.append("missing 'calloutType'")
    elif not is_valid_callout_type(callout_type):
        errors.append(f"unknown calloutType '{callout_type}'")

    # Check 3: Required fields
    if callout_type and is_valid_callout_type(callout_type):
        required = get_required_fields(callout_type)
        for field in required:
            value = callout.get(field)
            if value is None or (isinstance(value, str) and not value.strip()):
                errors.append(f"missing required field '{field}' for {callout_type}")

    # Check 4: Numeric fields
    for field in POSITIVE_NUMERIC_FIELDS:
        value = callout.get(field)
        if value is None:
            continue
        if isinstance(value, (int, float)):
            if value < 0:
                errors.append(f"negative value for '{field}': {value}")
        elif isinstance(value, str):
            # String values are OK pre-normalization (they get converted later)
            pass

    # Check 5: Angle fields
    for field in ANGLE_FIELDS:
        value = callout.get(field)
        if value is None:
            continue
        try:
            angle = float(value) if isinstance(value, str) else value
            if not (0 <= angle <= 360):
                errors.append(f"angle out of range for '{field}': {value}")
        except (ValueError, TypeError):
            pass  # Non-numeric angles are OK pre-normalization

    # Check 6: Quantity fields
    for field in QUANTITY_FIELDS:
        value = callout.get(field)
        if value is None:
            continue
        try:
            qty = int(value)
            if qty <= 0:
                errors.append(f"non-positive quantity for '{field}': {value}")
        except (ValueError, TypeError):
            errors.append(f"non-integer quantity for '{field}': {value}")

    # Build result
    if errors:
        error_msg = "; ".join(errors)
        repaired = dict(callout)
        repaired["_original_calloutType"] = callout.get("calloutType", "")
        repaired["calloutType"] = "Unknown"
        repaired["_invalid"] = True
        repaired["_validation_error"] = error_msg
        return repaired, False, error_msg

    return callout, True, None


def validate_and_repair_all(
    callouts: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    Validate and repair a list of callouts.

    Invalid callouts are NOT dropped -- they become Unknown with error info.

    Args:
        callouts: List of parsed callout dicts

    Returns:
        Tuple of (repaired_callouts, stats)
        stats = {"valid": N, "invalid": N, "total": N, "errors": {"reason": count}}
    """
    repaired: List[Dict[str, Any]] = []
    stats: Dict[str, Any] = {"valid": 0, "invalid": 0, "total": len(callouts), "errors": {}}

    for callout in callouts:
        result, is_valid, error = validate_callout(callout)
        repaired.append(result)

        if is_valid:
            stats["valid"] += 1
        else:
            stats["invalid"] += 1
            if error:
                # Track error types
                for e in error.split("; "):
                    stats["errors"][e] = stats["errors"].get(e, 0) + 1

    return repaired, stats


