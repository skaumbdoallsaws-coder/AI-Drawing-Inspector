"""Sketch Dimension Intent Map.

Feature intent names what a SolidWorks feature controls. This module
adds the next layer down: reviewed names for dimensions owned by a
consumed sketch, e.g. ``D1@Sketch270`` -> ``front strut diameter``.

The map is intentionally curator-first. We do not infer sketch
semantics from geometry yet; operator-reviewed entries are persisted
and used to pre-fill Sage/SolidWorks handoffs.
"""

from .builder import (
    SCHEMA_VERSION,
    sketch_dimension_intent_map_path,
    load_sketch_dimension_intent_map,
    write_sketch_dimension_intent_map,
)
from .lookup import (
    list_sketch_dimension_intents,
    lookup_sketch_dimension_intent,
)

__all__ = [
    "SCHEMA_VERSION",
    "sketch_dimension_intent_map_path",
    "load_sketch_dimension_intent_map",
    "write_sketch_dimension_intent_map",
    "list_sketch_dimension_intents",
    "lookup_sketch_dimension_intent",
]
