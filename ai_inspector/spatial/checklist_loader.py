"""ASME checklist loader.

Pure data loader — reads checklist.json files from the ASME feature
reference directories. No AI calls, no prompt construction.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .asme_mapper import get_all_categories

logger = logging.getLogger(__name__)

# Foundational categories — disabled to reduce noise and let the model
# focus on feature-specific checklists (Countersink, Hole, TappedHole, etc.)
_FOUNDATIONAL_CATEGORIES = ()


def load_checklists_for_profile(
    profile: dict,
    asme_refs_dir: str = "asme_feature_references",
) -> dict[str, dict]:
    """Load relevant ASME checklists for an inspection profile.

    1. Extracts feature types from ``profile['features']``.
    2. Maps them to ASME categories via :func:`asme_mapper.get_all_categories`.
    3. Always includes ``Dimension_Basics`` and ``Line_Conventions``.
    4. Loads ``checklist.json`` for each category from *asme_refs_dir*.

    Args:
        profile: An inspection profile dict with a ``features`` key containing
            a list of dicts, each having a ``type`` string.
        asme_refs_dir: Path to the directory containing ASME reference
            sub-folders (e.g. ``asme_feature_references/Hole/checklist.json``).

    Returns:
        Dict keyed by category name (e.g. ``'Hole'``, ``'Dimension_Basics'``)
        to the parsed checklist JSON. Missing or unreadable checklists are
        skipped with a warning.
    """
    refs_path = Path(asme_refs_dir)

    # Extract feature types from profile
    features = profile.get("features", [])
    feature_types = [f.get("type", "") for f in features if isinstance(f, dict)]

    # Get ASME categories for these feature types
    categories = get_all_categories(feature_types)

    # Always include foundational categories
    for cat in _FOUNDATIONAL_CATEGORIES:
        categories.add(cat)

    # Load checklists
    checklists: dict[str, dict] = {}
    for category in sorted(categories):
        checklist_path = refs_path / category / "checklist.json"
        if not checklist_path.exists():
            logger.warning(
                "ASME checklist not found: %s (skipping)", checklist_path
            )
            continue
        try:
            with open(checklist_path, "r", encoding="utf-8") as f:
                checklists[category] = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(
                "Failed to load ASME checklist %s: %s (skipping)",
                checklist_path,
                exc,
            )

    return checklists
