"""ASME feature type mapper.

Maps inspection profile feature type strings to ASME reference folder names.
Uses keyword matching with priority ordering so that more specific types
(e.g. 'Tapped blind hole') are matched before generic ones ('Hole').
"""

from __future__ import annotations

# Priority-ordered mapping rules.
# Each tuple is (keywords_any_must_match, exclude_keywords, asme_category).
# Rules are checked top-to-bottom; first match wins.
_MAPPING_RULES: list[tuple[list[str], list[str], str]] = [
    # --- Tapped / threaded holes (highest priority) ---
    (["tapped"], [], "TappedHole"),
    (["threaded"], [], "TappedHole"),
    # External threads also map to TappedHole reference
    (["thread"], [], "TappedHole"),

    # --- Counterbore (before generic 'hole') ---
    (["counterbore"], [], "Counterbore"),
    (["cbore"], [], "Counterbore"),
    (["counter bore"], [], "Counterbore"),

    # --- Countersink (before generic 'hole') ---
    (["countersink"], [], "Countersink"),
    (["csink"], [], "Countersink"),
    (["counter sink"], [], "Countersink"),

    # --- Spotface ---
    (["spotface"], [], "Spotface"),
    (["spot face"], [], "Spotface"),

    # --- Chamfer ---
    (["chamfer"], [], "Chamfer"),

    # --- Fillet / Radius ---
    (["fillet"], [], "Fillet_Radius"),
    (["radius"], ["bend"], "Fillet_Radius"),
    (["rounded"], ["slot"], "Fillet_Radius"),

    # --- Slot ---
    (["slot"], [], "Slot"),

    # --- Keyseat / Keyway ---
    (["keyseat"], [], "Keyseat"),
    (["keyway"], [], "Keyseat"),

    # --- Knurl ---
    (["knurl"], [], "Knurl"),

    # --- Taper / Conical ---
    (["taper"], [], "ConicalTaper"),
    (["conical"], [], "ConicalTaper"),

    # --- Generic hole / bore / through-hole (lowest priority among hole types) ---
    (["hole"], [], "Hole"),
    (["bore"], [], "Hole"),
    (["through-hole"], [], "Hole"),
]


def map_feature_type(feature_type: str) -> str | None:
    """Map a profile feature type string to an ASME reference category.

    Args:
        feature_type: The feature type string from an inspection profile,
            e.g. ``'Blind hole'``, ``'Tapped through-hole'``, ``'Edge chamfer'``.

    Returns:
        ASME category folder name (e.g. ``'Hole'``, ``'TappedHole'``,
        ``'Chamfer'``), or ``None`` if no mapping exists.
    """
    lower = feature_type.lower()

    for keywords, excludes, category in _MAPPING_RULES:
        # Check if any keyword matches
        if any(kw in lower for kw in keywords):
            # Check exclusions
            if excludes and any(ex in lower for ex in excludes):
                continue
            return category

    return None


def get_all_categories(feature_types: list[str]) -> set[str]:
    """Return the unique set of ASME categories for a list of feature types.

    Args:
        feature_types: List of feature type strings from a profile's features.

    Returns:
        Set of ASME category names (e.g. ``{'Hole', 'TappedHole', 'Chamfer'}``).
        Only includes types that have a valid mapping; unmapped types are skipped.
    """
    categories: set[str] = set()
    for ft in feature_types:
        cat = map_feature_type(ft)
        if cat is not None:
            categories.add(cat)
    return categories
