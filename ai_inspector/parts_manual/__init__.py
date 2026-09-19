"""Illustrated parts manual planning foundation."""

from .catalog import assembly_source_revision, build_occurrence_catalog, build_scoped_bom
from .artifacts import (
    PartsManualRenderArtifactError,
    attach_render_artifacts,
    render_artifact_path,
    store_render_artifact,
)
from .document import (
    MANUAL_SECTION_BOM_ROWS_PER_PAGE,
    PARTS_MANUAL_DOCUMENT_SCHEMA_VERSION,
    build_manual_document,
)
from .documentation import (
    DOCUMENTATION_COMMAND_ACTORS,
    DOCUMENTATION_COMMAND_OPERATIONS,
    DOCUMENTATION_SCENE_SCHEMA_VERSION,
    DOCUMENTATION_TARGET_TYPES,
    DocumentationSceneBindingError,
    DocumentationSceneConflictError,
    DocumentationSceneError,
    DocumentationSceneNotFoundError,
    DocumentationSceneRepository,
    canonical_documentation_bytes,
    documentation_scene_revision,
    replay_documentation_commands,
    validate_documentation_scene,
)
from .repository import (
    PartsManualConflictError,
    PartsManualNotFoundError,
    PartsManualRepository,
    PartsManualRepositoryError,
    PartsManualSourceConflictError,
    canonical_manual_bytes,
    manual_plan_revision,
)
from .pdf import (
    PartsManualPdfError,
    build_manual_pdf_bytes,
    manual_pdf_path,
    store_manual_pdf,
)
from .planner import (
    PARTS_MANUAL_PROPOSAL_SCHEMA_VERSION,
    PartsManualProposalError,
    compile_manual_structure_proposal,
)
from .quality import (
    audit_manual_plan,
    is_publishable_section_name,
    require_publishable_manual_plan,
)
from .schema import (
    MANUAL_CAMERA_PRESETS,
    MANUAL_EXPLODE_STRATEGIES,
    MANUAL_SECTION_SOURCES,
    PARTS_MANUAL_SCHEMA_VERSION,
    PartsManualValidationError,
    default_section_visualization,
    require_valid_manual_plan,
    validate_manual_plan,
)
from .version import (
    PARTS_MANUAL_DEFAULT_END_CONDITION,
    PARTS_MANUAL_RENDER_PIPELINE_VERSION,
)

__all__ = [
    "MANUAL_SECTION_SOURCES",
    "MANUAL_SECTION_BOM_ROWS_PER_PAGE",
    "MANUAL_CAMERA_PRESETS",
    "MANUAL_EXPLODE_STRATEGIES",
    "PARTS_MANUAL_SCHEMA_VERSION",
    "PARTS_MANUAL_DOCUMENT_SCHEMA_VERSION",
    "PARTS_MANUAL_PROPOSAL_SCHEMA_VERSION",
    "PARTS_MANUAL_DEFAULT_END_CONDITION",
    "PARTS_MANUAL_RENDER_PIPELINE_VERSION",
    "DOCUMENTATION_COMMAND_ACTORS",
    "DOCUMENTATION_COMMAND_OPERATIONS",
    "DOCUMENTATION_SCENE_SCHEMA_VERSION",
    "DOCUMENTATION_TARGET_TYPES",
    "DocumentationSceneBindingError",
    "DocumentationSceneConflictError",
    "DocumentationSceneError",
    "DocumentationSceneNotFoundError",
    "DocumentationSceneRepository",
    "PartsManualConflictError",
    "PartsManualNotFoundError",
    "PartsManualPdfError",
    "PartsManualProposalError",
    "PartsManualRenderArtifactError",
    "PartsManualRepository",
    "PartsManualRepositoryError",
    "PartsManualSourceConflictError",
    "PartsManualValidationError",
    "assembly_source_revision",
    "audit_manual_plan",
    "attach_render_artifacts",
    "build_occurrence_catalog",
    "build_manual_document",
    "build_manual_pdf_bytes",
    "compile_manual_structure_proposal",
    "build_scoped_bom",
    "canonical_manual_bytes",
    "canonical_documentation_bytes",
    "documentation_scene_revision",
    "manual_plan_revision",
    "manual_pdf_path",
    "is_publishable_section_name",
    "render_artifact_path",
    "store_render_artifact",
    "store_manual_pdf",
    "replay_documentation_commands",
    "default_section_visualization",
    "require_valid_manual_plan",
    "require_publishable_manual_plan",
    "validate_manual_plan",
    "validate_documentation_scene",
]
