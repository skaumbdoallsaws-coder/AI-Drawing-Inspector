"""Part Semantic Region Builder (MVP, deterministic heuristics).

Groups low-level GLB nodes / CAD features into user-facing regions
("top wing", "tail", "propeller") so Sage and the highlighting layer
can answer high-level questions like "show me the fuselage" instead
of speaking in SolidWorks operation names.

This MVP uses spatial + name heuristics only -- no LLM calls. The
output is always marked reviewed:false so a future operator-tool
pass can curate and lock the groups.

See docs/semantic-regions-mvp.md (when written) for the rule rationale.
"""

from .builder import (
    EDIT_READINESS_VALUES,
    PLACEMENT_CAPABILITIES,
    PLACEMENT_SURFACE_ROLES,
    PLACEMENT_SURFACE_TYPES,
    SCHEMA_VERSION,
    SEMANTIC_REGIONS_FILENAME,
    build_draft_regions,
    semantic_regions_path,
    write_semantic_regions,
)
from .resolver import (
    MATCH_KINDS,
    ResolvedRegion,
    resolve_region_for_phrase,
    resolve_regions_for_phrases,
)

__all__ = [
    "EDIT_READINESS_VALUES",
    "MATCH_KINDS",
    "PLACEMENT_CAPABILITIES",
    "PLACEMENT_SURFACE_ROLES",
    "PLACEMENT_SURFACE_TYPES",
    "ResolvedRegion",
    "SCHEMA_VERSION",
    "SEMANTIC_REGIONS_FILENAME",
    "build_draft_regions",
    "resolve_region_for_phrase",
    "resolve_regions_for_phrases",
    "semantic_regions_path",
    "write_semantic_regions",
]
