"""Authoritative Facility Layout domain, persistence, and API boundary."""

from .api import create_facility_layout_router
from .authority_repository import (
    AuthorityDocumentEnvelope,
    AuthorityMutationResult,
    FacilityShellRepository,
    PolicySetRepository,
    RevisionedAuthorityRepository,
    VehicleProfileRepository,
    authority_revision,
)
from .authorization import (
    AuthorizationDecision,
    FacilityPrincipal,
    authorize_facility_action,
    local_facility_principal,
    require_facility_action,
)
from .canonical import (
    canonical_layout_bytes,
    canonicalize_layout,
    canonicalize_polygon,
    canonicalize_quaternion,
    layout_revision,
)
from .diff import build_exact_layout_diff, facility_layout_diff_hash
from .errors import (
    FacilityAuthorizationError,
    FacilityCompatibilityError,
    FacilityConflictError,
    FacilityIntegrityError,
    FacilityLayoutError,
    FacilityNotFoundError,
    FacilityValidationError,
)
from .migration import (
    MigrationBundle,
    detect_layout_compatibility,
    migrate_legacy_semantic_v02,
)
from .operations import (
    FacilityLayoutOperationError,
    apply_facility_layout_operations,
    create_layout_document,
    supported_facility_layout_operations,
)
from .repository import FacilityLayoutRepository
from .service import (
    FacilityDependencySnapshot,
    FacilityLayoutService,
    FacilitySpatialContext,
    coordinate_frame_fingerprint,
)
from .spatial import (
    CANDIDATE_POLICY_VERSION,
    SPATIAL_ENGINE_VERSION,
    SpatialRecord,
    UniformGridSpatialIndex,
    diagnose_layout,
    generate_placement_candidates,
    spatial_fingerprint,
)
from .spatial_executor import (
    FacilitySpatialExecutor,
    SpatialCancellationToken,
    SpatialExecutionCancelled,
    SpatialJob,
)
from .validate import validate_layout

__all__ = [
    "AuthorizationDecision",
    "AuthorityDocumentEnvelope",
    "AuthorityMutationResult",
    "FacilityAuthorizationError",
    "FacilityCompatibilityError",
    "FacilityConflictError",
    "FacilityDependencySnapshot",
    "FacilityIntegrityError",
    "FacilityLayoutError",
    "FacilityLayoutOperationError",
    "FacilityLayoutRepository",
    "FacilityLayoutService",
    "FacilityNotFoundError",
    "FacilityPrincipal",
    "FacilitySpatialContext",
    "FacilitySpatialExecutor",
    "FacilityShellRepository",
    "FacilityValidationError",
    "MigrationBundle",
    "PolicySetRepository",
    "RevisionedAuthorityRepository",
    "VehicleProfileRepository",
    "CANDIDATE_POLICY_VERSION",
    "SPATIAL_ENGINE_VERSION",
    "SpatialCancellationToken",
    "SpatialExecutionCancelled",
    "SpatialJob",
    "SpatialRecord",
    "UniformGridSpatialIndex",
    "apply_facility_layout_operations",
    "authority_revision",
    "authorize_facility_action",
    "build_exact_layout_diff",
    "canonical_layout_bytes",
    "canonicalize_layout",
    "canonicalize_polygon",
    "canonicalize_quaternion",
    "coordinate_frame_fingerprint",
    "create_facility_layout_router",
    "create_layout_document",
    "detect_layout_compatibility",
    "facility_layout_diff_hash",
    "diagnose_layout",
    "generate_placement_candidates",
    "layout_revision",
    "local_facility_principal",
    "migrate_legacy_semantic_v02",
    "require_facility_action",
    "supported_facility_layout_operations",
    "spatial_fingerprint",
    "validate_layout",
]
