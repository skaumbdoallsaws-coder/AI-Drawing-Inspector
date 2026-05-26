"""Dimension Intent Map.

A per-revision JSON sidecar that links drawing dimensions to the exact
SolidWorks driving dimension (D1@Sketch7 style) for the same physical
control. Bridges three artifacts that already exist independently:

  - semantic_regions.json     : phrase -> region -> cad features
  - feature_intent_map.json   : cad feature -> physical role + controls
  - drawing_map.json          : drawing annotations with featureName +
                                annotationName + dimensionValue
  - {pn}_dimension_descriptions.json : drawing dim id -> description
  - (forward) part.json cadDimensions : driving dim values + ownership

Output (per revision):

  parts/{pn}/{rev}/{pn}_dimension_intent_map.json

The matcher is conservative: high confidence requires an exact
drawing<->cad name match (the drawing already names the sketch +
short name) or a value match plus region + description corroboration.
When evidence is ambiguous it leaves a candidate at medium / low so
the curator can review.

Reviewed=true mappings are preserved verbatim on re-draft, matching
the feature_intent and semantic_regions preservation contract.
"""

from .builder import (
    SCHEMA_VERSION,
    DIMENSION_INTENT_MAP_FILENAME,
    build_draft_dimension_intent_map,
    dimension_intent_map_path,
    load_dimension_intent_map,
    write_dimension_intent_map,
    validate_mapping,
    MATCH_CONFIDENCE_VALUES,
)
from .lookup import (
    lookup_dimension_intent,
    lookup_dimension_intent_for_cad_dimension,
)

__all__ = [
    "SCHEMA_VERSION",
    "DIMENSION_INTENT_MAP_FILENAME",
    "MATCH_CONFIDENCE_VALUES",
    "build_draft_dimension_intent_map",
    "dimension_intent_map_path",
    "load_dimension_intent_map",
    "write_dimension_intent_map",
    "validate_mapping",
    "lookup_dimension_intent",
    "lookup_dimension_intent_for_cad_dimension",
]
