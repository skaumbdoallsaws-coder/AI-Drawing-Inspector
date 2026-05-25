"""Feature Intent Map v1.

A per-revision JSON sidecar that maps each CAD feature to a
physical, user-friendly description of WHAT it controls. The
purpose is to let Sage explain CAD changes in operator language
("the propeller blade thickness increased from 0.5 mm to 5.5 mm")
while preserving the exact SolidWorks feature + parameter data
for technical drill-down ("Technically, Boss-Extrude1 depth1_mm
changed.").

Pipeline:
    semantic_regions.json + feature_colors.json + part diff params
    -> rules.py (deterministic name+type heuristics)
    -> {pn}_feature_intent_map.json

Curator preservation: any entry with reviewed=true is copied
verbatim on re-draft, so an operator can hand-edit physicalName /
featureRole / controls and the heuristic builder will never
clobber the curated text.
"""

from .builder import (
    SCHEMA_VERSION,
    build_draft_intent_map,
    feature_intent_map_path,
    load_feature_intent_map,
    write_feature_intent_map,
    EDIT_ROLE_VALUES,
)
from .lookup import (
    lookup_feature_intent,
    intent_entry_physical_phrase_for_param,
)

__all__ = [
    "SCHEMA_VERSION",
    "EDIT_ROLE_VALUES",
    "build_draft_intent_map",
    "feature_intent_map_path",
    "load_feature_intent_map",
    "write_feature_intent_map",
    "lookup_feature_intent",
    "intent_entry_physical_phrase_for_param",
]
