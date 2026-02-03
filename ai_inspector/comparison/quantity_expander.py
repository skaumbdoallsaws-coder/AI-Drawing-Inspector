"""Quantity expansion for drawing callouts and SolidWorks features.

Expands quantity-bearing items into individual instances BEFORE matching,
so the matcher operates at the instance level.

Example:
    Drawing: "4X ⌀.500 THRU" (1 callout, qty=4)
    SW: Hole ⌀.500, instanceCount=4 (1 feature, qty=4)

    After expansion:
    Drawing: 4 individual Hole callouts
    SW: 4 individual Hole features

    Matcher sees 4 vs 4 instead of 1 vs 1.

MUST be called on BOTH sides before matching and evaluation.
"""

from copy import deepcopy
from typing import Any, Dict, List, Tuple

from .sw_extractor import SwFeature


def expand_drawing_callouts(callouts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Expand drawing callouts by their quantity field.

    A callout with quantity=4 becomes 4 individual callouts,
    each with quantity=1 and an _instance_index field.
    Callouts without quantity or quantity=1 pass through unchanged.

    Args:
        callouts: List of parsed callout dicts (may have "quantity" key)

    Returns:
        Expanded list of callouts with quantity=1 each
    """
    expanded = []

    for callout in callouts:
        qty = callout.get("quantity", 1)

        # Ensure qty is a valid positive integer
        try:
            qty = int(qty)
            if qty < 1:
                qty = 1
        except (ValueError, TypeError):
            qty = 1

        if qty == 1:
            # Pass through unchanged (add instance metadata)
            instance = dict(callout)
            instance["_instance_index"] = 0
            instance["_original_quantity"] = 1
            expanded.append(instance)
        else:
            # Expand into individual instances
            for i in range(qty):
                instance = deepcopy(callout)
                instance["quantity"] = 1
                instance["_instance_index"] = i
                instance["_original_quantity"] = qty
                expanded.append(instance)

    return expanded


def expand_sw_features(features: List[SwFeature]) -> List[SwFeature]:
    """
    Expand SolidWorks features by their quantity/instanceCount.

    A feature with quantity=4 becomes 4 individual SwFeature objects,
    each with quantity=1.

    Args:
        features: List of SwFeature objects

    Returns:
        Expanded list of SwFeature with quantity=1 each
    """
    expanded = []

    for feat in features:
        qty = feat.quantity

        # Ensure qty is valid
        try:
            qty = int(qty)
            if qty < 1:
                qty = 1
        except (ValueError, TypeError):
            qty = 1

        if qty == 1:
            expanded.append(feat)
        else:
            for i in range(qty):
                instance = SwFeature(
                    feature_type=feat.feature_type,
                    diameter_inches=feat.diameter_inches,
                    depth_inches=feat.depth_inches,
                    radius_inches=feat.radius_inches,
                    thread=deepcopy(feat.thread) if feat.thread else None,
                    quantity=1,
                    location=f"{feat.location}[{i}]" if feat.location else f"instance_{i}",
                    raw_data=feat.raw_data,
                    source=feat.source,
                )
                expanded.append(instance)

    return expanded


def expand_both_sides(
    drawing_callouts: List[Dict[str, Any]],
    sw_features: List[SwFeature],
) -> Tuple[List[Dict[str, Any]], List[SwFeature]]:
    """
    Expand both drawing callouts and SW features by quantity.

    This is the main entry point -- call BEFORE matching.

    Args:
        drawing_callouts: Parsed drawing callout dicts
        sw_features: SW feature objects

    Returns:
        Tuple of (expanded_callouts, expanded_sw_features)
    """
    return (
        expand_drawing_callouts(drawing_callouts),
        expand_sw_features(sw_features),
    )


def expansion_summary(
    original_callouts: List[Dict[str, Any]],
    expanded_callouts: List[Dict[str, Any]],
    original_sw: List[SwFeature],
    expanded_sw: List[SwFeature],
) -> Dict[str, Any]:
    """
    Summarize expansion results for debugging.

    Returns:
        Dict with before/after counts and expansion details
    """
    return {
        "drawing": {
            "before": len(original_callouts),
            "after": len(expanded_callouts),
            "expanded_count": len(expanded_callouts) - len(original_callouts),
        },
        "solidworks": {
            "before": len(original_sw),
            "after": len(expanded_sw),
            "expanded_count": len(expanded_sw) - len(original_sw),
        },
    }
