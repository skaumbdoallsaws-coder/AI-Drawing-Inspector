"""Principal-bound application service for Facility Layout v1."""

from __future__ import annotations

import hashlib
import json
import math
import threading
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from ai_inspector.transactions import (
    CommitResult,
    ExactBinding,
    MutationPlan,
    PreparedRecord,
    ProposalRecord,
    ReconciliationResult,
    TransactionAuthorizationError,
    TransactionBindingError,
    TransactionCancelledError,
    TransactionError,
    TransactionExpiredError,
    TransactionIdempotencyConflictError,
    TransactionNotFoundError,
    TransactionPreparedError,
    TransactionReplayError,
    TransactionValidationError,
)

from .authority_repository import (
    FacilityShellRepository,
    PolicySetRepository,
    VehicleProfileRepository,
    authority_revision,
)
from .authorization import FacilityPrincipal, require_facility_action
from .errors import (
    FacilityAuthorizationError,
    FacilityConflictError,
    FacilityLayoutError,
    FacilityNotFoundError,
    FacilityValidationError,
)
from .canonical import canonical_layout_bytes, canonicalize_layout, layout_revision
from .diff import build_exact_layout_diff, facility_layout_diff_hash
from .motion_package import (
    FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2,
    FacilityMotionPackageStore,
    build_facility_motion_package,
    build_facility_motion_package_v2,
    build_navigation_journey_motion_package,
    validate_facility_motion_package_for_playback,
)
from .motion_validation_context import (
    build_motion_validation_context_projection,
    build_motion_validation_context_spec,
    motion_validation_context_fingerprint,
)
from .navigation_validation import validate_manual_navigation_path
from .navigation_compiler import (
    FacilityNavigationSnapshotStore,
    compile_navigation_snapshot as compile_navigation_snapshot_package,
    navigation_snapshot_summary,
)
from .journey_planning import (
    FacilityJourneySolutionStore,
    journey_solution_summary,
    plan_pedestrian_journey,
    plan_vehicle_journey,
)
from .navigation_handoffs import (
    FacilityNavigationHandoffStore,
    compile_handoff_topology,
    handoff_topology_summary,
)
from .motion_lanes import (
    FACILITY_MOTION_LANE_BINDING_VERSION,
    derive_directional_lane,
    inward_lane_binding_candidate,
    inset_lane_endpoints,
)
from .navigation_contract import seal_journey_solution
from .activity_scenario import (
    FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS,
    FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS,
    FacilityActivityScenarioStore,
    build_facility_activity_scenario,
    build_navigation_activity_scenario,
    facility_activity_scenario_summary,
)
from .activity_artifact_cache import (
    FacilityActivityScenarioArtifactCache,
)
from .navigation_activity import build_navigation_activity_presentation
from .movement_inventory import contained_area_zone_labels, enumerate_area
from .prototype_actor_profile import build_prototype_actor_profile
from .prototype_itinerary import (
    REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT,
    REFERENCE_COMPLETE_ACTIVITY_COMPILER_REVISION,
    REFERENCE_COMPLETE_ACTIVITY_PRESET,
    REFERENCE_DOWNSTREAM_ACTIVITY_PRESET,
    REFERENCE_DOWNSTREAM_ROOT_ZONE_LABEL,
    assert_itinerary_binding,
    build_prototype_itinerary,
)
from .reference_finished_goods import (
    REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
    REFERENCE_FINISHED_GOODS_PRESETS,
    REFERENCE_FINISHED_GOODS_SCHEMA_VERSION,
    derive_reference_finished_goods_cycle,
)
from .reference_receiving import (
    REFERENCE_RECEIVING_PLANNER_GRID_METERS,
    REFERENCE_RECEIVING_PUTAWAY_PRESET,
    derive_reference_receiving_cycles,
)
from .navigation_baseline import (
    NAV0_OPERATOR_ASSET_ID,
    NAV0_REFERENCE_LAYOUT_ID,
    NAV0_REFERENCE_LAYOUT_REVISION,
    NAV0_VEHICLE_CANDIDATES,
)
from .activity_visuals import activity_visual_alignment
from .lean_motion import (
    build_facility_lean_motion,
    derive_facility_lean_motion_blueprint,
)
from .operations import apply_facility_layout_operations
from .planner import (
    FACILITY_LAYOUT_ALTERNATIVE_POLICY_VERSION,
    FACILITY_LAYOUT_PLANNER_VERSION,
    FacilityLayoutPlanningError,
    generate_layout_proposals,
    validate_layout_request,
)
from .plan_settings import shell_with_plan_boundary
from .repository import FacilityLayoutRepository
from .routing import (
    ROUTER_VERSION,
    ROUTING_ENGINE_VERSION,
    generate_connector_candidates,
    normalized_cardinal_route_heading,
    persisted_route_fingerprint,
    plan_forklift_route,
    resolve_endpoint,
    route_traversable_corridor,
    routing_layout_fingerprint,
    validate_facility_aisle_route,
    validate_route,
    validate_utility_network,
)
from .spatial import (
    CANDIDATE_POLICY_VERSION,
    SPATIAL_ENGINE_VERSION,
    placement_clearance_records,
    placement_spatial_records,
    point_in_polygon,
    shell_obstacle_records,
)
from .spatial_executor import FacilitySpatialExecutor
from .transaction_adapter import (
    FacilityLayoutTransactionRuntime,
    deterministic_facility_proposal_id,
    facility_layout_binding,
    facility_transaction_target,
)
from .validate import validate_layout


DependencyResolver = Callable[
    [FacilityPrincipal, str, str, str],
    Mapping[str, Any] | bool | None,
]
CurrentAssetResolver = Callable[
    [FacilityPrincipal, str, str],
    Mapping[str, Any] | bool | None,
]
ProcessMapResolver = Callable[
    [FacilityPrincipal, str, str, str, str],
    Mapping[str, Any] | bool | None,
]


FACILITY_ACTIVITY_ENDPOINT_TURN_SECONDS = 1.0
EvidenceAuthorityResolver = Callable[
    [FacilityPrincipal, str, tuple[str, ...]],
    Mapping[str, Any] | None,
]


def _normalized_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise FacilityValidationError(
                "invalid_dependency_value",
                "A referenced dependency contains a non-finite number.",
            )
        rounded = round(value, 6)
        if rounded == 0:
            return 0
        return int(rounded) if rounded.is_integer() else rounded
    if isinstance(value, Mapping):
        return {
            str(key): _normalized_value(item)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_normalized_value(item) for item in value]
    return value


def _canonical_value_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            _normalized_value(value),
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise FacilityValidationError(
            "invalid_dependency_value",
            "A referenced dependency is not canonical JSON.",
        ) from exc


def coordinate_frame_fingerprint(frame: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_value_bytes(frame)).hexdigest()


def _dependency_unavailable(kind: str) -> None:
    raise FacilityValidationError(
        "dependency_resolver_unavailable",
        f"{kind} dependency validation is unavailable.",
        details={"dependencyKind": kind},
    )


def _published_authority_dependency(
    repository: Any,
    principal: FacilityPrincipal,
    *,
    site_id: str,
    authority_id: str,
    revision: str,
    kind: str,
    stale_if_missing: bool = False,
) -> Any:
    try:
        return repository.get_published(
            principal,
            site_id=site_id,
            authority_id=authority_id,
            revision=revision,
        )
    except FacilityNotFoundError as error:
        if not stale_if_missing:
            raise
        raise FacilityConflictError(
            f"stale_{kind}_revision",
            f"Referenced {kind} revision is stale.",
            details={
                "dependencyId": authority_id,
                "expectedRevision": revision,
            },
        ) from error


def _require_resolved(
    value: Mapping[str, Any] | bool | None,
    *,
    kind: str,
    identifier: str,
    revision: str,
) -> None:
    if value is None or value is False:
        raise FacilityNotFoundError(
            "not_found",
            "Facility resource was not found.",
        )
    if not isinstance(value, Mapping):
        if kind == "process_map":
            raise FacilityValidationError(
                "process_map_revision_unverified",
                "Process Map dependency did not return revision-bearing data.",
                details={
                    "dependencyId": identifier,
                    "expectedRevision": revision,
                },
            )
        return
    reported_revision = value.get("revision")
    if reported_revision is None:
        reported_revision = value.get(f"{kind}Revision")
    if reported_revision is None and kind == "process_map":
        raise FacilityValidationError(
            "process_map_revision_unverified",
            "Process Map dependency did not report its current revision.",
            details={
                "dependencyId": identifier,
                "expectedRevision": revision,
            },
        )
    if reported_revision is not None and reported_revision != revision:
        raise FacilityConflictError(
            f"stale_{kind}_revision",
            f"Referenced {kind} revision is stale.",
            details={
                "dependencyId": identifier,
                "expectedRevision": revision,
                "currentRevision": reported_revision,
            },
        )


@dataclass(frozen=True)
class FacilityDependencySnapshot:
    shell_revision: str
    policy_revision: str
    asset_revisions: tuple[tuple[str, str], ...]
    vehicle_revisions: tuple[tuple[str, str], ...]
    process_map_revisions: tuple[tuple[str, str, str], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "shellRevision": self.shell_revision,
            "policyRevision": self.policy_revision,
            "assetRevisions": [
                {"assetId": asset_id, "assetDefinitionRevision": revision}
                for asset_id, revision in self.asset_revisions
            ],
            "vehicleRevisions": [
                {"vehicleProfileId": vehicle_id, "vehicleProfileRevision": revision}
                for vehicle_id, revision in self.vehicle_revisions
            ],
            "processMapRevisions": [
                {
                    "productId": product_id,
                    "processMapId": map_id,
                    "processMapRevision": revision,
                }
                for product_id, map_id, revision in self.process_map_revisions
            ],
        }


@dataclass(frozen=True)
class FacilitySpatialContext:
    """Revision-bound inputs consumed by the authoritative spatial engine."""

    shell: Mapping[str, Any]
    policy_set: Mapping[str, Any]
    asset_definitions: Mapping[tuple[str, str], Mapping[str, Any]]
    evidence_authority: Mapping[str, Mapping[str, Any]]


class FacilityLayoutService:
    """Coordinate repositories while retaining deterministic domain authority."""

    def __init__(
        self,
        *,
        layout_repository: FacilityLayoutRepository,
        shell_repository: FacilityShellRepository,
        policy_repository: PolicySetRepository,
        vehicle_repository: VehicleProfileRepository,
        asset_definition_resolver: Optional[DependencyResolver] = None,
        current_asset_definition_resolver: Optional[
            CurrentAssetResolver
        ] = None,
        component_inventory_resolver: Callable[
            [FacilityPrincipal, Mapping[str, str], str, str], Mapping[str, Any]
        ] | None = None,
        process_map_resolver: Optional[ProcessMapResolver] = None,
        evidence_authority_resolver: Optional[
            EvidenceAuthorityResolver
        ] = None,
        spatial_executor: Optional[FacilitySpatialExecutor] = None,
        transaction_runtime: Optional[
            FacilityLayoutTransactionRuntime
        ] = None,
        motion_package_store: Optional[FacilityMotionPackageStore] = None,
        activity_scenario_store: Optional[FacilityActivityScenarioStore] = None,
        activity_scenario_artifact_cache: Optional[
            FacilityActivityScenarioArtifactCache
        ] = None,
        navigation_snapshot_store: Optional[
            FacilityNavigationSnapshotStore
        ] = None,
        journey_solution_store: Optional[FacilityJourneySolutionStore] = None,
        navigation_handoff_store: Optional[
            FacilityNavigationHandoffStore
        ] = None,
        capability_gate: Callable[[str], None] | None = None,
        allow_prototype_motion: bool = False,
        allow_legacy_lean_motion_fixture: bool = False,
    ) -> None:
        self.layout_repository = layout_repository
        self.shell_repository = shell_repository
        self.policy_repository = policy_repository
        self.vehicle_repository = vehicle_repository
        self.asset_definition_resolver = asset_definition_resolver
        self.current_asset_definition_resolver = (
            current_asset_definition_resolver
        )
        self.component_inventory_resolver = component_inventory_resolver
        self.process_map_resolver = process_map_resolver
        self.evidence_authority_resolver = evidence_authority_resolver
        self.spatial_executor = spatial_executor or FacilitySpatialExecutor()
        self.transaction_runtime = (
            transaction_runtime or FacilityLayoutTransactionRuntime()
        )
        self.motion_package_store = (
            motion_package_store or FacilityMotionPackageStore()
        )
        self.activity_scenario_store = (
            activity_scenario_store or FacilityActivityScenarioStore()
        )
        self.activity_scenario_artifact_cache = (
            activity_scenario_artifact_cache
            or FacilityActivityScenarioArtifactCache(
                self.layout_repository.root
                / ".derived"
                / "activity-scenarios"
            )
        )
        self.navigation_snapshot_store = (
            navigation_snapshot_store or FacilityNavigationSnapshotStore()
        )
        self.journey_solution_store = (
            journey_solution_store or FacilityJourneySolutionStore()
        )
        self.navigation_handoff_store = (
            navigation_handoff_store or FacilityNavigationHandoffStore()
        )
        self._navigation_snapshot_owner_lock = threading.RLock()
        self._navigation_snapshot_owners: dict[
            str, tuple[str, str, str]
        ] = {}
        self._journey_solution_owner_lock = threading.RLock()
        self._journey_solution_owners: dict[
            str, tuple[str, str, str]
        ] = {}
        self._navigation_handoff_owner_lock = threading.RLock()
        self._navigation_handoff_owners: dict[
            str, tuple[str, str, str]
        ] = {}
        self._reference_complete_scenario_lock = threading.RLock()
        self._reference_complete_scenario_ids: dict[
            tuple[str, str, str, str, str, int], str
        ] = {}
        self.capability_gate = capability_gate
        self.allow_prototype_motion = bool(allow_prototype_motion)
        self.allow_legacy_lean_motion_fixture = bool(
            allow_legacy_lean_motion_fixture
        )

    def _require_capability(self, capability: str) -> None:
        if self.capability_gate is not None:
            self.capability_gate(capability)

    @staticmethod
    def _collect_evidence_authority(
        values: Iterable[Mapping[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Normalize already-validated authority states.

        Claim payloads are deliberately ignored. An embedded
        ``evidenceStatus`` describes the claim but cannot prove source trust,
        freshness, non-revocation, or derivation validity.
        """

        authority: dict[str, dict[str, Any]] = {}
        for value in values:
            if not isinstance(value, Mapping):
                continue
            states = value.get("states")
            if not isinstance(states, list):
                continue
            for raw in states:
                if not isinstance(raw, Mapping):
                    continue
                evidence_id = raw.get("evidenceId")
                status = raw.get("status")
                blockers = raw.get("blockers")
                if (
                    not isinstance(evidence_id, str)
                    or not evidence_id
                    or status not in {"authored", "derived", "inferred", "unknown"}
                    or raw.get("current") is not True
                    or not isinstance(blockers, list)
                ):
                    continue
                normalized = {
                    "status": status,
                    "current": True,
                    "authoritative": raw.get("authoritative") is True,
                    "blockers": sorted(
                        str(item)
                        for item in blockers
                        if isinstance(item, str) and item
                    ),
                }
                previous = authority.get(evidence_id)
                if previous is not None and previous != normalized:
                    authority[evidence_id] = {
                        "status": "unknown",
                        "current": False,
                        "authoritative": False,
                        "blockers": ["evidence_state_conflict"],
                    }
                else:
                    authority[evidence_id] = normalized
        return {key: authority[key] for key in sorted(authority)}

    @staticmethod
    def _collect_evidence_refs(
        values: Iterable[Mapping[str, Any]],
    ) -> tuple[str, ...]:
        references: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, Mapping):
                raw = value.get("evidence")
                if isinstance(raw, list):
                    references.update(
                        str(item)
                        for item in raw
                        if isinstance(item, str) and item
                    )
                for item in value.values():
                    visit(item)
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        for item in values:
            visit(item)
        return tuple(sorted(references))

    def _resolve_asset_dependency(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        asset_id: str,
        revision: str,
    ) -> tuple[dict[str, Any], Mapping[str, Any] | None]:
        if self.asset_definition_resolver is None:
            _dependency_unavailable("asset_definition")
        resolved = self.asset_definition_resolver(
            principal,
            site_id,
            asset_id,
            revision,
        )
        _require_resolved(
            resolved,
            kind="asset_definition",
            identifier=asset_id,
            revision=revision,
        )
        if not isinstance(resolved, Mapping):
            raise FacilityValidationError(
                "asset_geometry_unavailable",
                "Asset definition geometry is unavailable.",
                details={"assetId": asset_id, "assetDefinitionRevision": revision},
            )
        raw_definition = resolved.get("definition", resolved)
        if not isinstance(raw_definition, Mapping):
            raise FacilityValidationError(
                "asset_geometry_unavailable",
                "Asset definition geometry is unavailable.",
                details={"assetId": asset_id, "assetDefinitionRevision": revision},
            )
        definition = deepcopy(dict(raw_definition))
        if not isinstance(definition.get("geometry"), Mapping):
            raise FacilityValidationError(
                "asset_geometry_unavailable",
                "Asset definition has no authoritative placement geometry.",
                details={"assetId": asset_id, "assetDefinitionRevision": revision},
            )
        definition.setdefault("assetId", asset_id)
        definition.setdefault("assetDefinitionRevision", revision)
        validation = resolved.get("evidenceValidation")
        return (
            definition,
            deepcopy(dict(validation))
            if isinstance(validation, Mapping)
            else None,
        )

    def _resolve_asset_definition(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        asset_id: str,
        revision: str,
    ) -> dict[str, Any]:
        return self._resolve_asset_dependency(
            principal,
            site_id,
            asset_id,
            revision,
        )[0]

    def _spatial_context(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
        *,
        additional_asset_refs: Iterable[tuple[str, str]] = (),
    ) -> FacilitySpatialContext:
        shell_ref = document["sourceShellRef"]
        shell = _published_authority_dependency(
            self.shell_repository,
            principal,
            site_id=site_id,
            authority_id=shell_ref["shellId"],
            revision=shell_ref["shellRevision"],
            kind="shell",
        )
        policy_ref = document["policySetRef"]
        policy = _published_authority_dependency(
            self.policy_repository,
            principal,
            site_id=site_id,
            authority_id=policy_ref["policySetId"],
            revision=policy_ref["policySetRevision"],
            kind="policy",
        )
        refs = {
            (
                str(placement["assetId"]),
                str(placement["assetDefinitionRevision"]),
            )
            for placement in document.get("placements", [])
            if isinstance(placement, Mapping)
        }
        refs.update(
            (str(asset_id), str(revision))
            for asset_id, revision in additional_asset_refs
        )
        resolved_assets = {
            (asset_id, revision): self._resolve_asset_dependency(
                principal,
                site_id,
                asset_id,
                revision,
            )
            for asset_id, revision in sorted(refs)
        }
        definitions = {
            key: value[0] for key, value in resolved_assets.items()
        }
        trusted_validations = [
            value[1]
            for value in resolved_assets.values()
            if isinstance(value[1], Mapping)
        ]
        effective_shell = shell_with_plan_boundary(shell.document, document)
        evidence_values = [
            shell.document,
            policy.document,
            *definitions.values(),
        ]
        evidence_refs = self._collect_evidence_refs(evidence_values)
        if self.evidence_authority_resolver is not None:
            resolved_authority = self.evidence_authority_resolver(
                principal,
                site_id,
                evidence_refs,
            )
            if isinstance(resolved_authority, Mapping):
                trusted_validations.append(resolved_authority)
        authority = self._collect_evidence_authority(trusted_validations)
        return FacilitySpatialContext(
            shell=effective_shell,
            policy_set=deepcopy(policy.document),
            asset_definitions=definitions,
            evidence_authority=authority,
        )

    def effective_shell(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
    ) -> dict[str, Any]:
        """DOCUMENT's shell as the spatial checks see it (its own features plus the layout's perimeter and interior
        walls and ground), with no asset reads: where the lighting estimate finds the building's walls."""
        shell_ref = document["sourceShellRef"]
        shell = _published_authority_dependency(
            self.shell_repository,
            principal,
            site_id=site_id,
            authority_id=shell_ref["shellId"],
            revision=shell_ref["shellRevision"],
            kind="shell",
        )
        return shell_with_plan_boundary(shell.document, document)

    def _diagnose_spatial(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
    ) -> dict[str, Any]:
        context = self._spatial_context(principal, site_id, document)
        return self.spatial_executor.run_diagnostics(
            document,
            context.asset_definitions,
            shell=context.shell,
            policy_set=context.policy_set,
            evidence_authority=context.evidence_authority,
        )

    @staticmethod
    def _require_spatially_valid(diagnostics: Mapping[str, Any]) -> None:
        errors = [
            deepcopy(dict(item))
            for item in diagnostics.get("findings", [])
            if isinstance(item, Mapping) and item.get("severity") == "error"
        ]
        if errors:
            raise FacilityValidationError(
                "spatial_validation_failed",
                "Facility Layout violates authoritative spatial constraints.",
                details={
                    "safetyStatus": diagnostics.get("safetyStatus"),
                    "findings": errors,
                    "metrics": deepcopy(diagnostics.get("metrics", {})),
                },
            )

    @staticmethod
    def _spatial_error_key(finding: Mapping[str, Any]) -> tuple[Any, ...]:
        return (
            str(finding.get("code") or ""),
            tuple(
                sorted(
                    str(item)
                    for item in finding.get("subjectRefs", [])
                    if isinstance(item, str) and item
                )
            ),
        )

    @classmethod
    def _require_no_new_spatial_errors(
        cls,
        baseline: Mapping[str, Any],
        candidate: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
        baseline_layout: Mapping[str, Any] | None = None,
    ) -> None:
        """Reject hard findings introduced by a proposed transaction.

        P6 can open layouts authored before authoritative spatial validation
        existed. Those findings remain visible and unsafe, but they must not
        deadlock unrelated authoring or remediation. A transaction may retain
        or remove an existing finding; it may never add a new finding.
        """

        baseline_keys = {
            cls._spatial_error_key(item)
            for item in baseline.get("findings", [])
            if isinstance(item, Mapping) and item.get("severity") == "error"
        }
        introduced = [
            deepcopy(dict(item))
            for item in candidate.get("findings", [])
            if (
                isinstance(item, Mapping)
                and item.get("severity") == "error"
                and cls._spatial_error_key(item) not in baseline_keys
            )
        ]
        # A populated legacy or manually authored layout may receive its first
        # workcell zone after equipment has already been placed. Preserve the
        # resulting containment findings in diagnostics, but do not make that
        # incremental zone-authoring gesture impossible. The exception is
        # intentionally narrow: only untouched placements in a previously
        # unzoned layout qualify. Mixed batches cannot grandfather equipment
        # they also edit. Other hard spatial findings remain blocking.
        adds_first_zone = (
            isinstance(baseline_layout, Mapping)
            and baseline_layout.get("zones") == []
        ) and any(
            isinstance(operation, Mapping)
            and operation.get("op") == "add_zone"
            for operation in (operations or [])
        )
        existing_placement_ids = {
            str(placement.get("placementId") or "")
            for placement in (
                baseline_layout.get("placements", [])
                if isinstance(baseline_layout, Mapping)
                else []
            )
            if isinstance(placement, Mapping) and placement.get("placementId")
        }
        if adds_first_zone and introduced:
            # Use the operation engine's affected IDs, including indirect and
            # multi-placement edits, rather than maintaining another op list.
            affected_ids = apply_facility_layout_operations(
                baseline_layout, operations or []
            )["affectedIds"]
            existing_placement_ids.difference_update(affected_ids)

        def is_incremental_zone_finding(finding: Mapping[str, Any]) -> bool:
            details = finding.get("details")
            refs = [
                str(item)
                for item in finding.get("subjectRefs", [])
                if isinstance(item, str) and item
            ]
            return (
                adds_first_zone
                and finding.get("code") == "zone_containment_violation"
                and isinstance(details, Mapping)
                and details.get("reason") == "footprint_or_setback"
                and len(refs) == 1
                and refs[0] in existing_placement_ids
            )

        blocking = [
            item for item in introduced
            if not is_incremental_zone_finding(item)
        ]
        if blocking:
            raise FacilityValidationError(
                "spatial_validation_failed",
                "Facility Layout transaction introduces authoritative spatial "
                "constraint violations.",
                details={
                    "safetyStatus": candidate.get("safetyStatus"),
                    "findings": blocking,
                    "baselineErrorCount": len(baseline_keys),
                    "metrics": deepcopy(candidate.get("metrics", {})),
                },
            )

    @staticmethod
    def _routing_finding(
        code: str,
        severity: str,
        message: str,
        *subjects: str,
        details: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        subject_refs = sorted(str(item) for item in subjects if item)
        finding_id = (
            "frf-"
            + hashlib.sha256(
                _canonical_value_bytes(
                    {
                        "code": code,
                        "severity": severity,
                        "subjectRefs": subject_refs,
                        "details": dict(details or {}),
                    }
                )
            ).hexdigest()[:24]
        )
        result = {
            "findingId": finding_id,
            "findingType": "facility_routing",
            "code": code,
            "severity": severity,
            "message": message,
            "subjectRefs": subject_refs,
        }
        if details:
            result["details"] = deepcopy(dict(details))
        return result

    @staticmethod
    def _routing_error_key(finding: Mapping[str, Any]) -> tuple[Any, ...]:
        raw_subjects = finding.get("subjectRefs")
        if not isinstance(raw_subjects, list):
            raw_subjects = finding.get("subjects", [])
        return (
            str(finding.get("code") or ""),
            tuple(
                sorted(
                    str(item)
                    for item in raw_subjects
                    if isinstance(item, str)
                )
            ),
        )

    @classmethod
    def _require_no_new_routing_errors(
        cls,
        baseline: Mapping[str, Any],
        candidate: Mapping[str, Any],
    ) -> None:
        baseline_keys = {
            cls._routing_error_key(item)
            for item in baseline.get("findings", [])
            if isinstance(item, Mapping)
            and item.get("severity") in {"error", "blocked"}
        }
        introduced = [
            deepcopy(dict(item))
            for item in candidate.get("findings", [])
            if isinstance(item, Mapping)
            and item.get("severity") in {"error", "blocked"}
            and cls._routing_error_key(item) not in baseline_keys
        ]
        if introduced:
            raise FacilityValidationError(
                "routing_validation_failed",
                "Facility Layout transaction introduces routing violations.",
                details={
                    "findings": introduced,
                    "baselineErrorCount": len(baseline_keys),
                },
            )

    @staticmethod
    def _require_routing_valid(diagnostics: Mapping[str, Any]) -> None:
        errors = [
            deepcopy(dict(item))
            for item in diagnostics.get("findings", [])
            if isinstance(item, Mapping)
            and item.get("severity") in {"error", "blocked"}
        ]
        if errors:
            raise FacilityValidationError(
                "routing_validation_failed",
                "Facility Layout violates authoritative routing constraints.",
                details={"findings": errors},
            )

    @staticmethod
    def _process_map_document(value: Mapping[str, Any]) -> Mapping[str, Any] | None:
        for key in ("document", "processMap", "map", "layout"):
            candidate = value.get(key)
            if isinstance(candidate, Mapping):
                return candidate
        if any(key in value for key in ("canvasNodes", "nodes", "canvasEdges", "edges")):
            return value
        return None

    def _process_binding_findings(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        binding: Mapping[str, Any],
        facility_document: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        binding_id = str(binding.get("processBindingId") or "")
        if self.process_map_resolver is None:
            return [
                self._routing_finding(
                    "process_map_structure_unavailable",
                    "blocked",
                    "Process Map structure cannot be verified.",
                    binding_id,
                )
            ]
        resolved = self.process_map_resolver(
            principal,
            site_id,
            str(binding.get("productId") or ""),
            str(binding.get("processMapId") or ""),
            str(binding.get("processMapRevision") or ""),
        )
        if not isinstance(resolved, Mapping):
            return [
                self._routing_finding(
                    "process_map_structure_unavailable",
                    "blocked",
                    "Process Map resolver did not return revision-bound structure.",
                    binding_id,
                )
            ]
        reported_revision = resolved.get("revision")
        if reported_revision is None:
            reported_revision = resolved.get("processMapRevision")
        requested_revision = str(binding.get("processMapRevision") or "")
        if reported_revision is None:
            return [
                self._routing_finding(
                    "process_map_revision_unverified",
                    "blocked",
                    "Process Map resolver did not report its current revision.",
                    binding_id,
                    details={"expectedRevision": requested_revision},
                )
            ]
        if reported_revision != requested_revision:
            return [
                self._routing_finding(
                    "stale_process_map_revision",
                    "blocked",
                    "Process Map binding revision is stale.",
                    binding_id,
                    details={
                        "expectedRevision": requested_revision,
                        "currentRevision": reported_revision,
                    },
                )
            ]
        document = self._process_map_document(resolved)
        if document is None:
            return [
                self._routing_finding(
                    "process_map_structure_unavailable",
                    "blocked",
                    "Process Map resolver did not return revision-bound structure.",
                    binding_id,
                )
            ]
        raw_nodes = document.get("canvasNodes", document.get("nodes", []))
        raw_edges = document.get("canvasEdges", document.get("edges", []))
        node_ids = {
            str(item.get("id"))
            for item in raw_nodes
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        } if isinstance(raw_nodes, list) else set()
        edge_ids = {
            str(item.get("id"))
            for item in raw_edges
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        } if isinstance(raw_edges, list) else set()
        findings: list[dict[str, Any]] = []
        missing_nodes = sorted(
            str(item)
            for item in binding.get("processNodeIds", [])
            if str(item) not in node_ids
        )
        missing_edges = sorted(
            str(item)
            for item in binding.get("processEdgeIds", [])
            if str(item) not in edge_ids
        )
        if missing_nodes:
            findings.append(
                self._routing_finding(
                    "dangling_process_binding_node",
                    "error",
                    "Process binding references unknown Process Map nodes.",
                    binding_id,
                    *missing_nodes,
                    details={"missingNodeIds": missing_nodes},
                )
            )
        if missing_edges:
            findings.append(
                self._routing_finding(
                    "dangling_process_binding_edge",
                    "error",
                    "Process binding references unknown Process Map edges.",
                    binding_id,
                    *missing_edges,
                    details={"missingEdgeIds": missing_edges},
                )
            )
        binding_role = str(binding.get("bindingRole") or "")
        node_by_id = {
            str(item.get("id")): item
            for item in raw_nodes
            if isinstance(item, Mapping) and isinstance(item.get("id"), str)
        } if isinstance(raw_nodes, list) else {}
        route_by_id = {
            str(item.get("routeId")): item
            for item in facility_document.get("routes", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("routeId"), str)
        }
        bound_node_ids = [
            str(item) for item in binding.get("processNodeIds", [])
        ]
        bound_edge_ids = [
            str(item) for item in binding.get("processEdgeIds", [])
        ]
        bound_placement_ids = [
            str(item) for item in binding.get("placementIds", [])
        ]
        bound_route_ids = [
            str(item) for item in binding.get("routeIds", [])
        ]
        node_roles = {"resource", "inspection", "storage", "staging"}
        edge_roles = {"material_flow", "operator_flow"}
        if binding_role in node_roles:
            if not bound_node_ids or not bound_placement_ids:
                findings.append(
                    self._routing_finding(
                        "process_binding_semantics_invalid",
                        "error",
                        "This binding role requires Process Map nodes and facility placements.",
                        binding_id,
                        binding_role,
                    )
                )
            junction_ids = sorted(
                node_id
                for node_id in bound_node_ids
                if (
                    node_id in node_by_id
                    and str(node_by_id[node_id].get("type") or "")
                    == "junction"
                )
            )
            if junction_ids:
                findings.append(
                    self._routing_finding(
                        "process_binding_semantics_invalid",
                        "error",
                        "Routing junctions cannot represent assigned work or resources.",
                        binding_id,
                        *junction_ids,
                    )
                )
        if binding_role in edge_roles:
            if not bound_edge_ids or not bound_route_ids:
                findings.append(
                    self._routing_finding(
                        "process_binding_semantics_invalid",
                        "error",
                        "Flow bindings require Process Map edges and facility routes.",
                        binding_id,
                        binding_role,
                    )
                )
            expected_route_kinds = (
                {"material", "conveyor", "forklift"}
                if binding_role == "material_flow"
                else {"operator"}
            )
            incompatible_routes = sorted(
                route_id
                for route_id in bound_route_ids
                if route_id in route_by_id
                and str(route_by_id[route_id].get("routeKind") or "")
                not in expected_route_kinds
            )
            if incompatible_routes:
                findings.append(
                    self._routing_finding(
                        "process_binding_semantics_invalid",
                        "error",
                        "Bound facility route kind is incompatible with the binding role.",
                        binding_id,
                        *incompatible_routes,
                        details={
                            "bindingRole": binding_role,
                            "allowedRouteKinds": sorted(
                                expected_route_kinds
                            ),
                        },
                    )
                )
        return findings

    @staticmethod
    def _route_obstacles(
        document: Mapping[str, Any],
        asset_definitions: Mapping[tuple[str, str], Mapping[str, Any]],
        shell: Mapping[str, Any],
        *,
        excluded_placement_ids: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        excluded = excluded_placement_ids or set()
        result: list[dict[str, Any]] = []
        for placement in document.get("placements", []):
            if (
                not isinstance(placement, Mapping)
                or placement.get("placementId") in excluded
            ):
                continue
            key = (
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            )
            asset = asset_definitions.get(key)
            if asset is None:
                continue
            for record in placement_spatial_records(placement, asset):
                result.append(
                    {
                        "obstacleId": record.record_id,
                        "boundary": [
                            {"x": point[0], "z": point[1]}
                            for point in record.polygon
                        ],
                    }
                )
        for record in shell_obstacle_records(shell):
            result.append(
                {
                    "obstacleId": record.record_id,
                    "boundary": [
                        {"x": point[0], "z": point[1]}
                        for point in record.polygon
                    ],
                }
            )
        result.sort(key=lambda item: item["obstacleId"])
        return result

    def circulation_obstacle_context(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
        *,
        vehicle_profile_ref: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Snapshot authority-bound static geometry for one durable G2.2 run."""

        context = self._spatial_context(principal, site_id, document)
        obstacles: list[dict[str, Any]] = []
        for placement in document.get("placements", []):
            if not isinstance(placement, Mapping):
                continue
            key = (
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            )
            asset = context.asset_definitions.get(key)
            if asset is None:
                continue
            for record in placement_spatial_records(placement, asset):
                obstacles.append({
                    "obstacleId": record.record_id,
                    "obstacleKind": "placement_footprint",
                    "boundary": [
                        {"x": point[0], "z": point[1]}
                        for point in record.polygon
                    ],
                    "evidenceStatus": "derived",
                    "sourceRef": record.owner_id,
                })
            for record in placement_clearance_records(
                placement,
                asset,
                evidence_authority=context.evidence_authority,
            ):
                if not record.authoritative:
                    continue
                obstacles.append({
                    "obstacleId": record.record_id,
                    "obstacleKind": "authored_clearance_envelope",
                    "boundary": [
                        {"x": point[0], "z": point[1]}
                        for point in record.polygon
                    ],
                    "evidenceStatus": record.evidence_status,
                    "sourceRef": record.clearance_id or record.owner_id,
                })
        shell_kind_by_id = {
            str(feature.get("featureId") or ""): str(
                feature.get("featureKind") or "shell_obstacle"
            )
            for feature in context.shell.get("features", [])
            if isinstance(feature, Mapping)
        }
        for record in shell_obstacle_records(context.shell):
            obstacles.append({
                "obstacleId": record.record_id,
                "obstacleKind": shell_kind_by_id.get(
                    record.owner_id, "shell_obstacle"
                ),
                "boundary": [
                    {"x": point[0], "z": point[1]}
                    for point in record.polygon
                ],
                "evidenceStatus": "authored",
                "sourceRef": record.owner_id,
            })
        vehicle_profile = None
        if isinstance(vehicle_profile_ref, Mapping):
            vehicle_id = str(
                vehicle_profile_ref.get("vehicleProfileId") or ""
            )
            vehicle_revision = str(
                vehicle_profile_ref.get("vehicleProfileRevision") or ""
            )
            if not vehicle_id or not vehicle_revision:
                raise FacilityValidationError(
                    "invalid_vehicle_route_request",
                    "Vehicle profile ID and revision are required together.",
                )
            envelope = self.vehicle_repository.get_published(
                principal,
                site_id=site_id,
                authority_id=vehicle_id,
                revision=vehicle_revision,
            )
            vehicle_profile = {
                "document": deepcopy(dict(envelope.document)),
                "revision": envelope.revision,
                "status": envelope.status,
            }
        source_revisions = {
            "layout": hashlib.sha256(
                _canonical_value_bytes(document)
            ).hexdigest(),
            "shell": str(
                document.get("sourceShellRef", {}).get("shellRevision") or ""
            ),
            "policy": str(
                document.get("policySetRef", {}).get("policySetRevision") or ""
            ),
        }
        for asset_id, revision in sorted(context.asset_definitions):
            source_revisions[f"asset:{asset_id}"] = revision
        if vehicle_profile is not None:
            source_revisions[
                f"vehicle:{vehicle_profile['document']['vehicleProfileId']}"
            ] = vehicle_profile["revision"]
        return {
            "schemaVersion": 1,
            "obstacles": sorted(
                obstacles, key=lambda item: item["obstacleId"]
            ),
            "sourceRevisions": source_revisions,
            "vehicleProfile": vehicle_profile,
        }

    def _diagnose_routing(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
    ) -> dict[str, Any]:
        context = self._spatial_context(principal, site_id, document)
        traversable = [
            deepcopy(zone.get("boundary"))
            for zone in document.get("zones", [])
            if isinstance(zone, Mapping)
            and zone.get("zoneType") == "aisle"
            and isinstance(zone.get("boundary"), list)
        ]
        findings: list[dict[str, Any]] = []
        route_results = []
        for route in sorted(
            (
                item
                for item in document.get("routes", [])
                if isinstance(item, Mapping)
            ),
            key=lambda item: str(item.get("routeId") or ""),
        ):
            extensions = route.get("extensions")
            if (
                isinstance(extensions, Mapping)
                and isinstance(extensions.get("facilityAisle"), Mapping)
            ):
                result = validate_facility_aisle_route(document, route)
                route_results.append(result)
                findings.extend(result["findings"])
                continue
            vehicle_profile = None
            vehicle_ref = route.get("vehicleProfileRef")
            if isinstance(vehicle_ref, Mapping):
                envelope = self.vehicle_repository.get_published(
                    principal,
                    site_id=site_id,
                    authority_id=str(vehicle_ref.get("vehicleProfileId") or ""),
                    revision=str(vehicle_ref.get("vehicleProfileRevision") or ""),
                )
                vehicle_profile = envelope.document
            result = validate_route(
                document,
                route,
                asset_definitions=context.asset_definitions,
                shell={"document": context.shell, "revision": context.shell.get("revision")},
                shell_revision=str(
                    document.get("sourceShellRef", {}).get("shellRevision") or ""
                ),
                vehicle_profile=vehicle_profile,
                traversable_polygons=traversable,
                obstacles=self._route_obstacles(
                    document,
                    context.asset_definitions,
                    context.shell,
                    excluded_placement_ids=set(),
                ),
            )
            route_results.append(result)
            findings.extend(result["findings"])
        utility_results = []
        for network in sorted(
            (
                item
                for item in document.get("utilityNetworks", [])
                if isinstance(item, Mapping)
            ),
            key=lambda item: str(item.get("utilityNetworkId") or ""),
        ):
            result = validate_utility_network(
                document,
                network,
                asset_definitions=context.asset_definitions,
                shell={"document": context.shell, "revision": (
                    document.get("sourceShellRef", {}).get("shellRevision")
                )},
                shell_revision=str(
                    document.get("sourceShellRef", {}).get("shellRevision") or ""
                ),
                obstacles=self._route_obstacles(
                    document,
                    context.asset_definitions,
                    context.shell,
                    excluded_placement_ids=set(),
                ),
            )
            utility_results.append(result)
            findings.extend(result["findings"])
        for binding in sorted(
            (
                item
                for item in document.get("processBindings", [])
                if isinstance(item, Mapping)
            ),
            key=lambda item: str(item.get("processBindingId") or ""),
        ):
            findings.extend(
                self._process_binding_findings(
                    principal,
                    site_id,
                    binding,
                    document,
                )
            )
        ordered = sorted(
            (deepcopy(dict(item)) for item in findings),
            key=lambda item: (
                {"error": 0, "blocked": 1, "warning": 2, "info": 3}.get(
                    str(item.get("severity")),
                    9,
                ),
                str(item.get("code") or ""),
                str(item.get("findingId") or ""),
            ),
        )
        return {
            "routingEngineVersion": ROUTING_ENGINE_VERSION,
            "valid": not any(
                item.get("severity") in {"error", "blocked"}
                for item in ordered
            ),
            "findings": ordered,
            "routes": route_results,
            "utilityNetworks": utility_results,
            "metrics": {
                "routeCount": len(route_results),
                "utilityNetworkCount": len(utility_results),
                "processBindingCount": len(document.get("processBindings", [])),
                "errorCount": sum(
                    item.get("severity") == "error" for item in ordered
                ),
                "blockedCount": sum(
                    item.get("severity") == "blocked" for item in ordered
                ),
            },
        }
    def _revalidate_route_layout_sources(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
        *,
        inherited_routes: Iterable[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
        """Rebind unchanged inherited routes only after candidate validation."""
        candidate = deepcopy(dict(document))
        routing = self._diagnose_routing(principal, site_id, candidate)
        inherited = {route["routeId"]: route for route in inherited_routes}
        results = {result["routeId"]: result for result in routing["routes"]}
        layout_fingerprint = routing_layout_fingerprint(candidate)
        rebound_ids = []
        for route in candidate.get("routes", []):
            route_id = route["routeId"]
            if route != inherited.get(route_id):
                continue
            extensions = route.get("extensions", {})
            if isinstance(extensions, Mapping) and isinstance(
                extensions.get("facilityAisle"), Mapping
            ):
                continue
            if not route.get("sourceRevisions", {}).get("layout"):
                continue
            errors = [
                finding for finding in results[route_id]["findings"]
                if finding.get("severity") in {"error", "blocked"}
            ]
            # Validate with the original binding first. External staleness,
            # endpoint/geometry tampering and swept-volume failures cannot be
            # repaired by updating a revision. Never rewrite submitted routes.
            if not errors or any(
                finding.get("code") != "stale_route_source_revision"
                or set(finding.get("subjects", [])) != {route_id, "layout"}
                for finding in errors
            ):
                continue
            route["sourceRevisions"]["layout"] = layout_fingerprint
            route["routeFingerprint"] = persisted_route_fingerprint(route)
            rebound_ids.append(route_id)
        if rebound_ids:
            candidate = canonicalize_layout(candidate)
            routing = self._diagnose_routing(principal, site_id, candidate)
        return candidate, routing, sorted(rebound_ids)

    def validate_dependencies(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
        *,
        stale_missing_authorities: bool = False,
    ) -> FacilityDependencySnapshot:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        validate_layout(document)
        association = document["association"]
        if association["siteId"] != site_id:
            raise FacilityNotFoundError(
                "not_found",
                "Facility resource was not found.",
            )

        shell_ref = document["sourceShellRef"]
        shell = _published_authority_dependency(
            self.shell_repository,
            principal,
            site_id=site_id,
            authority_id=shell_ref["shellId"],
            revision=shell_ref["shellRevision"],
            kind="shell",
            stale_if_missing=stale_missing_authorities,
        )
        shell_frame = shell.document["coordinateFrame"]
        if _canonical_value_bytes(shell_frame) != _canonical_value_bytes(
            document["coordinateFrame"]
        ):
            raise FacilityValidationError(
                "invalid_coordinate_frame",
                "Layout and Facility Shell coordinate frames differ.",
            )
        expected_frame_fingerprint = coordinate_frame_fingerprint(shell_frame)
        if (
            shell_ref["coordinateFrameFingerprint"]
            != expected_frame_fingerprint
        ):
            raise FacilityConflictError(
                "stale_shell_revision",
                "Facility Shell coordinate-frame fingerprint is stale.",
                details={
                    "expectedCoordinateFrameFingerprint": (
                        expected_frame_fingerprint
                    )
                },
            )

        policy_ref = document["policySetRef"]
        policy = _published_authority_dependency(
            self.policy_repository,
            principal,
            site_id=site_id,
            authority_id=policy_ref["policySetId"],
            revision=policy_ref["policySetRevision"],
            kind="policy",
            stale_if_missing=stale_missing_authorities,
        )

        asset_revisions = sorted(
            {
                (
                    placement["assetId"],
                    placement["assetDefinitionRevision"],
                )
                for placement in document["placements"]
            }
        )
        if asset_revisions and self.asset_definition_resolver is None:
            _dependency_unavailable("asset_definition")
        decal_targets = {
            art["target"].get("placementId")
            for art in document.get("extensions", {}).get("facilityDecals", {}).get("artworks", [])
        }
        decal_wall_assets = {
            (placement["assetId"], placement["assetDefinitionRevision"])
            for placement in document["placements"] if placement["placementId"] in decal_targets
        }
        for asset_id, revision in asset_revisions:
            resolved = self.asset_definition_resolver(
                principal,
                site_id,
                asset_id,
                revision,
            )
            _require_resolved(
                resolved,
                kind="asset_definition",
                identifier=asset_id,
                revision=revision,
            )
            if (asset_id, revision) in decal_wall_assets:
                definition = resolved.get("definition", resolved) if isinstance(resolved, Mapping) else {}
                tags = definition.get("tags", [])
                bounds = definition.get("geometry", {}).get("aabb")
                if (definition.get("structureKind") != "wall" and "wall" not in tags) or not bounds:
                    raise FacilityValidationError(
                        "invalid_decal_target", "Decals require a wall asset with measured bounds.")

        vehicle_revisions = sorted(
            {
                (
                    route["vehicleProfileRef"]["vehicleProfileId"],
                    route["vehicleProfileRef"]["vehicleProfileRevision"],
                )
                for route in document["routes"]
                if isinstance(route.get("vehicleProfileRef"), Mapping)
            }
        )
        for vehicle_id, revision in vehicle_revisions:
            _published_authority_dependency(
                self.vehicle_repository,
                principal,
                site_id=site_id,
                authority_id=vehicle_id,
                revision=revision,
                kind="vehicle_profile",
                stale_if_missing=stale_missing_authorities,
            )

        process_revisions = sorted(
            {
                (
                    binding["productId"],
                    binding["processMapId"],
                    binding["processMapRevision"],
                )
                for binding in document["processBindings"]
            }
        )
        if process_revisions and self.process_map_resolver is None:
            _dependency_unavailable("process_map")
        for product_id, map_id, revision in process_revisions:
            resolved = self.process_map_resolver(
                principal,
                site_id,
                product_id,
                map_id,
                revision,
            )
            _require_resolved(
                resolved,
                kind="process_map",
                identifier=f"{product_id}:{map_id}",
                revision=revision,
            )

        return FacilityDependencySnapshot(
            shell_revision=shell.revision,
            policy_revision=policy.revision,
            asset_revisions=tuple(asset_revisions),
            vehicle_revisions=tuple(vehicle_revisions),
            process_map_revisions=tuple(process_revisions),
        )

    def list_layouts(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        *,
        include_archived: bool = False,
    ) -> dict[str, Any]:
        return self.layout_repository.list_layouts(
            principal,
            site_id,
            include_archived=include_archived,
        )

    def get_layout(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
    ) -> dict[str, Any]:
        return self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )

    def get_layout_revision(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        revision: str,
    ) -> dict[str, Any]:
        return self.layout_repository.get_layout_revision(
            principal,
            site_id,
            layout_id,
            revision,
        )

    def create_layout(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
        *,
        make_default: bool = False,
    ) -> dict[str, Any]:
        dependencies = self.validate_dependencies(
            principal,
            site_id,
            document,
        )
        spatial = self._diagnose_spatial(principal, site_id, document)
        self._require_spatially_valid(spatial)
        routing = self._diagnose_routing(principal, site_id, document)
        self._require_routing_valid(routing)
        result = self.layout_repository.create_layout(
            principal,
            site_id,
            document,
            make_default=make_default,
        )
        result["dependencies"] = dependencies.to_dict()
        result["spatialDiagnostics"] = spatial
        result["routingDiagnostics"] = routing
        return result

    def save_layout(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        document: Mapping[str, Any],
        base_revision: str,
        *,
        keep_zone_covers: bool = False,
    ) -> dict[str, Any]:
        if keep_zone_covers:
            document = self._kept_zone_covers(principal, site_id, layout_id, document)
        dependencies = self.validate_dependencies(
            principal,
            site_id,
            document,
        )
        spatial = self._diagnose_spatial(principal, site_id, document)
        self._require_spatially_valid(spatial)
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        baseline_routing = self._diagnose_routing(
            principal,
            site_id,
            current["layout"],
        )
        routing = self._diagnose_routing(principal, site_id, document)
        self._require_no_new_routing_errors(baseline_routing, routing)
        result = self.layout_repository.save_layout(
            principal,
            site_id,
            layout_id,
            document,
            base_revision,
        )
        result["dependencies"] = dependencies.to_dict()
        result["spatialDiagnostics"] = spatial
        result["routingDiagnostics"] = routing
        return result

    def _kept_zone_covers(self, principal, site_id, layout_id, document):
        """A whole-document save (the HTTP PUT) keeps zone ceilings and roofs as set_zone_ceiling and set_zone_roof
        left them (ceilings.keep_layout_zone_covers), 2026-11-03. A document that is one of the layout's saved
        revisions (Undo or a restore sending a whole earlier revision) is saved whole."""
        from .ceilings import keep_layout_zone_covers
        current = self.layout_repository.get_layout(principal, site_id, layout_id)
        try:
            revision = layout_revision(document)
        except (FacilityLayoutError, TypeError, ValueError, KeyError):
            revision = None
        if revision is not None and revision != current["revision"]:
            try:
                self.layout_repository.get_layout_revision(principal, site_id, layout_id, revision)
                return document
            except FacilityNotFoundError:
                pass
        try:
            return keep_layout_zone_covers(current["layout"], document)
        except ValueError as exc:
            # The document's own errors come first, as without the rule (a zone without an id sending a ceiling).
            validate_layout(document)
            raise FacilityValidationError("zone_ceiling_or_roof_kept", str(exc)) from exc

    def apply_operations(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        operations: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        operation_result, dependencies = self._prepare_operations(
            principal,
            site_id,
            layout_id,
            base_revision,
            operations,
        )
        saved = self.layout_repository.save_layout(
            principal,
            site_id,
            layout_id,
            operation_result["document"],
            base_revision,
        )
        return {
            **saved,
            "dependencies": dependencies.to_dict(),
            "operationResult": deepcopy(operation_result),
            "spatialDiagnostics": deepcopy(
                operation_result["spatialDiagnostics"]
            ),
            "routingDiagnostics": deepcopy(
                operation_result["routingDiagnostics"]
            ),
        }

    def preview_operations(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        operations: list[Mapping[str, Any]],
    ) -> dict[str, Any]:
        operation_result, dependencies = self._prepare_operations(
            principal,
            site_id,
            layout_id,
            base_revision,
            operations,
        )
        return {
            **deepcopy(operation_result),
            "revision": layout_revision(operation_result["document"]),
            "baseRevision": base_revision,
            "dependencies": dependencies.to_dict(),
        }

    def preview_program(self, principal, site_id, layout_id, base_revision, operation_plan):
        """Validate a server-compiled multi-batch program without saving a draft."""
        from .generation_requirements import guard_generation_operations
        from .program_execution import execute_facility_program_operation_plan
        require_facility_action(principal, tenant_id=principal.tenant_id, site_id=site_id, action="layout.edit")
        current = self.layout_repository.get_layout(principal, site_id, layout_id)
        if current["revision"] != base_revision or operation_plan.get("baseLayoutRevision") != base_revision:
            raise FacilityConflictError("revision_conflict", "Facility Layout revision conflict.")
        for stage in operation_plan.get("stages", []):
            for batch in stage.get("batches", []):
                if batch.get("operations"):
                    guard_generation_operations(batch["operations"])
        executed = execute_facility_program_operation_plan(current["layout"], operation_plan)
        document = executed["draftLayout"]
        dependencies = self.validate_dependencies(principal, site_id, document)
        spatial = self._diagnose_spatial(principal, site_id, document)
        self._require_spatially_valid(spatial)
        routing = self._diagnose_routing(principal, site_id, document)
        self._require_routing_valid(routing)
        latest = self.layout_repository.get_layout(principal, site_id, layout_id)
        if latest["revision"] != base_revision:
            raise FacilityConflictError("revision_conflict", "Facility Layout changed during validation.")
        return {"document": document, "revision": executed["draftLayoutRevision"], "baseRevision": base_revision,
                "dependencies": dependencies.to_dict(), "findings": [], "spatialDiagnostics": spatial,
                "routingDiagnostics": routing, "execution": executed}

    @staticmethod
    def _raise_transaction_error(error: TransactionError) -> None:
        details = {"transactionCode": error.code}
        if isinstance(error, TransactionNotFoundError):
            raise FacilityNotFoundError(
                error.code,
                str(error),
                details=details,
            ) from error
        if isinstance(error, TransactionAuthorizationError):
            raise FacilityAuthorizationError(
                error.code,
                str(error),
                details=details,
            ) from error
        if isinstance(
            error,
            (
                TransactionBindingError,
                TransactionCancelledError,
                TransactionExpiredError,
                TransactionIdempotencyConflictError,
                TransactionPreparedError,
                TransactionReplayError,
            ),
        ):
            raise FacilityConflictError(
                error.code,
                str(error),
                details=details,
            ) from error
        raise FacilityValidationError(
            error.code,
            str(error),
            details=details,
        ) from error

    @staticmethod
    def _planner_failure(error: FacilityLayoutPlanningError) -> None:
        raise FacilityValidationError(
            error.code,
            error.message,
            details=error.details,
        ) from error

    @staticmethod
    def _proposal_dependency_fingerprint(
        planner_result: Mapping[str, Any],
        alternative: Mapping[str, Any],
    ) -> str:
        return hashlib.sha256(
            _canonical_value_bytes(
                {
                    "alternativeId": alternative["alternativeId"],
                    "alternativePolicyVersion": (
                        FACILITY_LAYOUT_ALTERNATIVE_POLICY_VERSION
                    ),
                    "obstacleFingerprint": planner_result[
                        "obstacleFingerprint"
                    ],
                    "plannerDependencyFingerprint": planner_result[
                        "dependencyFingerprint"
                    ],
                    "plannerVersion": FACILITY_LAYOUT_PLANNER_VERSION,
                    "routerVersion": ROUTER_VERSION,
                    "routingEngineVersion": ROUTING_ENGINE_VERSION,
                    "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
                }
            )
        ).hexdigest()

    @classmethod
    def _alternative_binding(
        cls,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
        planner_result: Mapping[str, Any],
        alternative: Mapping[str, Any],
    ) -> ExactBinding:
        return facility_layout_binding(
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=layout_id,
            base_revision=str(planner_result["layoutRevision"]),
            diff_hash=str(alternative["operationReceipt"]["diffHash"]),
            dependency_fingerprint=cls._proposal_dependency_fingerprint(
                planner_result,
                alternative,
            ),
        )

    @staticmethod
    def _require_session_id(session_id: str) -> str:
        value = session_id.strip() if isinstance(session_id, str) else ""
        if not value or len(value) > 128:
            raise FacilityValidationError(
                "invalid_session_id",
                "A bounded editor session ID is required.",
            )
        return value

    @staticmethod
    def _assert_proposal_target(
        proposal: ProposalRecord,
        *,
        tenant_id: str,
        site_id: str,
        layout_id: str,
    ) -> None:
        if proposal.binding.target != facility_transaction_target(
            tenant_id=tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        ):
            raise FacilityNotFoundError(
                "proposal_not_found",
                "Facility Layout proposal was not found.",
            )

    @staticmethod
    def _source_revision_check(
        document: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> None:
        supplied = request.get("sourceRevisions", {})
        expected = {
            "shell": str(
                document.get("sourceShellRef", {}).get("shellRevision") or ""
            ),
            "policy": str(
                document.get("policySetRef", {}).get(
                    "policySetRevision"
                ) or ""
            ),
        }
        for key, current in expected.items():
            requested = supplied.get(key)
            if requested is not None and requested != current:
                raise FacilityConflictError(
                    f"stale_{key}_revision",
                    f"Planner request uses a stale {key} revision.",
                    details={
                        "expectedRevision": requested,
                        "currentRevision": current,
                    },
                )

    def _generate_layout_alternatives(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        stale_missing_dependencies: bool = False,
    ) -> dict[str, Any]:
        try:
            normalized_request = validate_layout_request(request)
        except FacilityLayoutPlanningError as error:
            self._planner_failure(error)
            raise AssertionError("unreachable")

        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        document = current["layout"]
        self.validate_dependencies(
            principal,
            site_id,
            document,
            stale_missing_authorities=stale_missing_dependencies,
        )
        self._source_revision_check(document, normalized_request)

        requested_asset_refs = {
            (
                str(item["assetId"]),
                str(item["assetDefinitionRevision"]),
            )
            for item in normalized_request["assetSet"]
        }
        context = self._spatial_context(
            principal,
            site_id,
            document,
            additional_asset_refs=requested_asset_refs,
        )
        asset_definitions = {
            asset_id: {
                "revision": revision,
                "document": deepcopy(definition),
            }
            for (asset_id, revision), definition in sorted(
                context.asset_definitions.items()
            )
        }
        vehicle_profiles: dict[str, dict[str, Any]] = {}
        for raw_route in normalized_request["routes"]:
            if not isinstance(raw_route, Mapping):
                continue
            vehicle_id = raw_route.get("vehicleProfileId")
            revision = raw_route.get("vehicleProfileRevision")
            if not isinstance(vehicle_id, str) or not isinstance(
                revision,
                str,
            ):
                continue
            envelope = _published_authority_dependency(
                self.vehicle_repository,
                principal,
                site_id=site_id,
                authority_id=vehicle_id,
                revision=revision,
                kind="vehicle_profile",
                stale_if_missing=stale_missing_dependencies,
            )
            profile = deepcopy(envelope.document)
            profile["vehicleProfileRevision"] = envelope.revision
            vehicle_profiles[vehicle_id] = profile
        try:
            result = generate_layout_proposals(
                document,
                normalized_request,
                asset_definitions,
                shell=context.shell,
                policy_set=context.policy_set,
                evidence_authority=context.evidence_authority,
                vehicle_profiles=vehicle_profiles,
            )
        except FacilityLayoutPlanningError as error:
            self._planner_failure(error)
            raise AssertionError("unreachable")

        for alternative in result["alternatives"]:
            prepared, dependencies = self._prepare_operations(
                principal,
                site_id,
                layout_id,
                base_revision,
                alternative["operations"],
                required_action=None,
            )
            if (
                prepared["diffHash"]
                != alternative["operationReceipt"]["diffHash"]
                or canonical_layout_bytes(prepared["document"])
                != canonical_layout_bytes(
                    alternative["ghostPreview"]["layout"]
                )
            ):
                raise FacilityConflictError(
                    "planner_preview_mismatch",
                    "Authoritative operation replay changed the proposal.",
                    details={
                        "alternativeId": alternative["alternativeId"]
                    },
                )
            binding = self._alternative_binding(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                layout_id=layout_id,
                planner_result=result,
                alternative=alternative,
            )
            alternative["transactionBinding"] = binding.to_dict()
            alternative["authoritativeDependencies"] = dependencies.to_dict()
            alternative["authoritativeDiagnostics"] = {
                "spatial": deepcopy(prepared["spatialDiagnostics"]),
                "routing": deepcopy(prepared["routingDiagnostics"]),
            }
        return result

    @staticmethod
    def _find_alternative(
        result: Mapping[str, Any],
        alternative_id: str,
    ) -> dict[str, Any]:
        alternative = next(
            (
                item
                for item in result.get("alternatives", [])
                if isinstance(item, Mapping)
                and item.get("alternativeId") == alternative_id
            ),
            None,
        )
        if alternative is None:
            raise FacilityConflictError(
                "layout_alternative_stale",
                "The approved layout alternative is no longer available.",
                details={"alternativeId": alternative_id},
            )
        return deepcopy(dict(alternative))

    def create_layout_proposals(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="proposal.create",
        )
        result = self._generate_layout_alternatives(
            principal,
            site_id,
            layout_id,
            base_revision,
            request,
        )
        public_alternatives = []
        selected_proposal_id = None
        for alternative in result["alternatives"]:
            binding = ExactBinding.from_dict(
                alternative["transactionBinding"]
            )
            proposal_type = (
                "layout-alternative:"
                + str(alternative["strategy"])
            )
            proposal_id = deterministic_facility_proposal_id(
                layout_id=layout_id,
                base_revision=base_revision,
                proposal_type=proposal_type,
                semantic_plan_hash=str(result["requestFingerprint"]),
                dependency_fingerprint=binding.dependency_fingerprint,
            )
            proposal = self.transaction_runtime.propose(
                tenant_id=principal.tenant_id,
                principal_id=principal.principal_id,
                proposal_id=proposal_id,
                binding=binding,
                payload={
                    "tenantId": principal.tenant_id,
                    "siteId": site_id,
                    "layoutId": layout_id,
                    "baseRevision": base_revision,
                    "proposalType": proposal_type,
                    "semanticPlanHash": str(result["requestFingerprint"]),
                    "request": deepcopy(dict(request)),
                    "alternativeId": alternative["alternativeId"],
                },
                public_summary={
                    "alternativeId": alternative["alternativeId"],
                    "strategy": alternative["strategy"],
                    "metrics": deepcopy(alternative["metrics"]),
                },
            )
            public = deepcopy(alternative)
            public["proposalId"] = proposal.proposal_id
            public["createdAt"] = proposal.created_at
            public["expiresAt"] = proposal.expires_at
            public_alternatives.append(public)
            if alternative["alternativeId"] == result[
                "selectedAlternativeId"
            ]:
                selected_proposal_id = proposal.proposal_id
        return {
            **{
                key: deepcopy(value)
                for key, value in result.items()
                if key != "alternatives"
            },
            "selectedProposalId": selected_proposal_id,
            "alternatives": public_alternatives,
        }

    def _regenerate_proposal(
        self,
        principal: FacilityPrincipal,
        proposal: ProposalRecord,
        *,
        site_id: str,
        layout_id: str,
    ) -> tuple[
        dict[str, Any],
        ExactBinding,
        dict[str, Any],
        FacilityDependencySnapshot,
    ]:
        self._assert_proposal_target(
            proposal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        )
        payload = proposal.payload
        if (
            payload.get("tenantId") != principal.tenant_id
            or payload.get("siteId") != site_id
            or payload.get("layoutId") != layout_id
        ):
            raise FacilityNotFoundError(
                "proposal_not_found",
                "Facility Layout proposal was not found.",
            )
        request = payload.get("request")
        if not isinstance(request, Mapping):
            raise FacilityConflictError(
                "proposal_payload_unavailable",
                "Facility Layout proposal inputs are unavailable.",
            )
        from .operation_proposals import PROPOSAL_TYPE, UNDO_TYPE, regenerate
        if payload.get("proposalType") in {PROPOSAL_TYPE, UNDO_TYPE}:
            return regenerate(self, principal, site_id, layout_id, payload)
        self._validate_current_proposal_asset_revisions(
            principal,
            site_id,
            request,
        )
        result = self._generate_layout_alternatives(
            principal,
            site_id,
            layout_id,
            str(payload.get("baseRevision") or ""),
            request,
            stale_missing_dependencies=True,
        )
        alternative = self._find_alternative(
            result,
            str(payload.get("alternativeId") or ""),
        )
        binding = ExactBinding.from_dict(
            alternative["transactionBinding"]
        )
        prepared, dependencies = self._prepare_operations(
            principal,
            site_id,
            layout_id,
            binding.base_revision,
            alternative["operations"],
            required_action=None,
        )
        return alternative, binding, prepared, dependencies

    def _validate_current_proposal_asset_revisions(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        request: Mapping[str, Any],
    ) -> None:
        asset_set = request.get("assetSet")
        if not isinstance(asset_set, list):
            return
        for raw in asset_set:
            if not isinstance(raw, Mapping):
                continue
            asset_id = raw.get("assetId")
            revision = raw.get("assetDefinitionRevision")
            if not isinstance(asset_id, str) or not isinstance(revision, str):
                continue
            if self.current_asset_definition_resolver is not None:
                resolved = self.current_asset_definition_resolver(
                    principal,
                    site_id,
                    asset_id,
                )
            elif self.asset_definition_resolver is not None:
                resolved = self.asset_definition_resolver(
                    principal,
                    site_id,
                    asset_id,
                    revision,
                )
            else:
                _dependency_unavailable("asset_definition")
            _require_resolved(
                resolved,
                kind="asset_definition",
                identifier=asset_id,
                revision=revision,
            )

    @staticmethod
    def _layout_content_fingerprint(
        document: Mapping[str, Any],
    ) -> str:
        # canonical_layout_bytes works on a detached copy, so a shallow one is enough here.
        candidate = dict(document)
        # Repository-owned timestamps change during an approved save and are
        # not part of the user-approved spatial content.
        candidate["createdAt"] = "__repository_timestamp__"
        candidate["updatedAt"] = "__repository_timestamp__"
        return hashlib.sha256(canonical_layout_bytes(candidate)).hexdigest()

    @staticmethod
    def _collection_receipt_summary(
        values: Any,
    ) -> dict[str, Any]:
        items = list(values) if isinstance(values, list) else []  # only hashed
        return {
            "count": len(items),
            "sha256": hashlib.sha256(
                _canonical_value_bytes(items)
            ).hexdigest(),
        }

    @classmethod
    def _diagnostic_receipt_summary(
        cls,
        diagnostics: Any,
    ) -> dict[str, Any]:
        value = dict(diagnostics) if isinstance(diagnostics, Mapping) else {}  # hashed; parts copied below
        findings = value.get("findings")
        summary = {
            "sha256": hashlib.sha256(
                _canonical_value_bytes(value)
            ).hexdigest(),
            "findings": cls._collection_receipt_summary(findings),
        }
        for key in (
            "valid",
            "safe",
            "safetyStatus",
            "spatialEngineVersion",
            "routingEngineVersion",
        ):
            if key in value:
                summary[key] = deepcopy(value[key])
        metrics = value.get("metrics")
        if isinstance(metrics, Mapping):
            summary["metrics"] = deepcopy(dict(metrics))
        return summary

    @classmethod
    def _compact_operation_result(
        cls,
        prepared: Mapping[str, Any],
    ) -> dict[str, Any]:
        document = prepared.get("document")
        document_timestamps = {}
        if isinstance(document, Mapping):
            document_timestamps = {
                key: deepcopy(document.get(key))
                for key in ("createdAt", "updatedAt")
                if key in document
            }
        canonical_diff = prepared.get("canonicalDiff")
        diff_summary: dict[str, Any] = {}
        if isinstance(canonical_diff, Mapping):
            diff_summary = {
                "schemaVersion": canonical_diff.get("schemaVersion"),
                "beforeRevision": canonical_diff.get("beforeRevision"),
                "afterRevision": canonical_diff.get("afterRevision"),
                "changed": bool(canonical_diff.get("changed")),
                "entries": cls._collection_receipt_summary(
                    canonical_diff.get("entries")
                ),
                "sha256": hashlib.sha256(
                    _canonical_value_bytes(canonical_diff)
                ).hexdigest(),
            }
        return {
            "schemaVersion": prepared.get("schemaVersion"),
            "changed": bool(prepared.get("changed")),
            "createdIds": deepcopy(prepared.get("createdIds") or []),
            "affectedIds": deepcopy(prepared.get("affectedIds") or []),
            "findings": cls._collection_receipt_summary(
                prepared.get("findings")
            ),
            "canonicalDiff": diff_summary,
            "diffHash": prepared.get("diffHash"),
            "operationResults": cls._collection_receipt_summary(
                prepared.get("operationResults")
            ),
            "spatialDiagnostics": cls._diagnostic_receipt_summary(
                prepared.get("spatialDiagnostics")
            ),
            "routingDiagnostics": cls._diagnostic_receipt_summary(
                prepared.get("routingDiagnostics")
            ),
            "documentTimestamps": document_timestamps,
        }

    @classmethod
    def _proposal_commit_payload(
        cls,
        alternative: Mapping[str, Any],
        prepared: Mapping[str, Any],
        dependencies: FacilityDependencySnapshot,
    ) -> dict[str, Any]:
        operation_result = cls._compact_operation_result(prepared)
        return {
            "dependencies": dependencies.to_dict(),
            "operationResult": operation_result,
            # The same summaries as the operation result's.
            "spatialDiagnostics": deepcopy(operation_result["spatialDiagnostics"]),
            "routingDiagnostics": deepcopy(operation_result["routingDiagnostics"]),
            "alternativeId": alternative["alternativeId"],
            "strategy": alternative["strategy"],
            "metrics": deepcopy(alternative["metrics"]),
            **({"requestedEditMode": alternative["editMode"],
                "directApplyPolicy": deepcopy(alternative["directApplyPolicy"])}
               if "directApplyPolicy" in alternative else {}),
        }

    @classmethod
    def _proposal_recovery_context(
        cls,
        alternative: Mapping[str, Any],
        prepared: Mapping[str, Any],
        dependencies: FacilityDependencySnapshot,
    ) -> dict[str, Any]:
        return {
            "schemaVersion": 2,
            "kind": "facility-layout-commit",
            "expectedChanged": bool(prepared.get("changed")),
            "expectedLayoutFingerprint": (
                cls._layout_content_fingerprint(prepared["document"])
            ),
            "commitPayload": cls._proposal_commit_payload(
                alternative,
                prepared,
                dependencies,
            ),
        }

    def _hydrate_proposal_commit_payload(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        revision: str,
        payload: Mapping[str, Any],
    ) -> dict[str, Any]:
        historical = self.layout_repository.get_layout_revision(
            principal,
            site_id,
            layout_id,
            revision,
        )
        document = deepcopy(historical["layout"])
        result = deepcopy(dict(payload))
        result["layout"] = document
        operation_result = result.get("operationResult")
        if isinstance(operation_result, Mapping):
            operation_result = deepcopy(dict(operation_result))
            if (
                "document" in operation_result
                and "documentTimestamps" not in operation_result
            ):
                result["operationResult"] = operation_result
                return result
            operation_document = deepcopy(document)
            timestamps = operation_result.pop(
                "documentTimestamps",
                {},
            )
            if isinstance(timestamps, Mapping):
                for key in ("createdAt", "updatedAt"):
                    if key in timestamps:
                        operation_document[key] = deepcopy(
                            timestamps[key]
                        )
            operation_result["document"] = operation_document
            result["operationResult"] = operation_result
        return result

    def get_layout_proposal_preview(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        proposal_id: str,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="proposal.read",
        )
        try:
            proposal = self.transaction_runtime.get_proposal(
                proposal_id,
                tenant_id=principal.tenant_id,
                site_id=site_id,
                layout_id=layout_id,
                principal_id=principal.principal_id,
            )
        except TransactionError as error:
            self._raise_transaction_error(error)
            raise AssertionError("unreachable")
        alternative, binding, _, _ = self._regenerate_proposal(
            principal,
            proposal,
            site_id=site_id,
            layout_id=layout_id,
        )
        return {
            "proposalId": proposal.proposal_id,
            "action": proposal.action,
            "alternative": alternative,
            "transactionBinding": binding.to_dict(),
            "createdAt": proposal.created_at,
            "expiresAt": proposal.expires_at,
            "previewPure": True,
        }

    def cancel_layout_proposal(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        proposal_id: str,
        session_id: str,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="proposal.dismiss",
        )
        self._require_session_id(session_id)
        try:
            proposal = self.transaction_runtime.get_proposal(
                proposal_id,
                tenant_id=principal.tenant_id,
                site_id=site_id,
                layout_id=layout_id,
                principal_id=principal.principal_id,
            )
            self._assert_proposal_target(
                proposal,
                tenant_id=principal.tenant_id,
                site_id=site_id,
                layout_id=layout_id,
            )
            cancelled = self.transaction_runtime.cancel(
                proposal_id,
                tenant_id=principal.tenant_id,
                site_id=site_id,
                layout_id=layout_id,
                principal_id=principal.principal_id,
                session_id=session_id,
            )
        except TransactionError as error:
            self._raise_transaction_error(error)
            raise AssertionError("unreachable")
        return cancelled.public_dict()

    def approve_layout_proposal(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        proposal_id: str,
        binding_value: Mapping[str, Any],
        *,
        session_id: str,
        idempotency_key: str,
        explicit_approval: bool,
        authorization_mode: str = "explicit",
        direct_consent: bool = False,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="proposal.approve",
        )
        self._require_session_id(session_id)
        try:
            binding = ExactBinding.from_dict(binding_value)
            if authorization_mode not in {"explicit", "direct"}:
                raise FacilityValidationError("invalid_authorization_mode", "Unknown edit authorization mode.")
            if authorization_mode == "direct":
                if direct_consent is not True:
                    raise FacilityValidationError("direct_consent_required", "Apply directly must be enabled by the user.")
                proposal = self.transaction_runtime.get_proposal(proposal_id,
                    tenant_id=principal.tenant_id, site_id=site_id, layout_id=layout_id,
                    principal_id=principal.principal_id)
                if (proposal.payload.get("editMode") != "direct"
                        or proposal.payload.get("proposalType") not in {"exact-operations-v1", "exact-undo-v1"}
                        or not proposal.public_summary.get("directApplyPolicy", {}).get("eligible")):
                    raise FacilityValidationError("direct_review_required", "This change requires preview and approval.")
                if self.get_layout(principal, site_id, layout_id)["revision"] != proposal.binding.base_revision:
                    raise FacilityConflictError("revision_conflict", "The layout changed before direct authorization.")
                # Standing consent authorizes only this validated exact batch.
                explicit_approval = True
            approval = self.transaction_runtime.approve(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                layout_id=layout_id,
                proposal_id=proposal_id,
                binding=binding,
                principal_id=principal.principal_id,
                session_id=session_id,
                idempotency_key=idempotency_key,
                explicit_approval=explicit_approval,
                authorization_mode=authorization_mode,
            )
        except TransactionError as error:
            self._raise_transaction_error(error)
            raise AssertionError("unreachable")
        return approval.public_dict()

    def apply_layout_proposal(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        approval_token: str,
        binding_value: Mapping[str, Any],
        *,
        session_id: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="proposal.apply",
        )
        self._require_session_id(session_id)
        service = self
        try:
            binding = ExactBinding.from_dict(binding_value)
        except TransactionError as error:
            self._raise_transaction_error(error)
            raise AssertionError("unreachable")

        class _FacilityApplyAdapter:
            def __init__(self) -> None:
                self.regenerated: tuple[Any, ...] | None = None

            def regenerate(
                self,
                proposal: ProposalRecord,
            ) -> MutationPlan:
                alternative, regenerated, prepared, dependencies = (
                    service._regenerate_proposal(
                        principal,
                        proposal,
                        site_id=site_id,
                        layout_id=layout_id,
                    )
                )
                # Kept here for commit (2026-11-02): the plan carries only
                # what the kernel keeps, not deep copies of both layouts.
                self.regenerated = (regenerated, alternative, prepared,
                                    dependencies)
                return MutationPlan(
                    binding=regenerated,
                    payload={"alternativeId": alternative["alternativeId"]},
                    recovery=service._proposal_recovery_context(
                        alternative,
                        prepared,
                        dependencies,
                    ),
                )

            def commit(self, plan: MutationPlan) -> CommitResult:
                if self.regenerated is None or self.regenerated[0] != plan.binding:
                    raise TransactionBindingError(
                        "transaction_binding_mismatch",
                        "Facility Layout changed during commit.",
                    )
                _, alternative, prepared, dependencies = self.regenerated
                operations = alternative["operations"]
                from .operation_proposals import PROPOSAL_TYPE, UNDO_TYPE, recheck
                exact = alternative["strategy"] in {PROPOSAL_TYPE, UNDO_TYPE}
                if exact:
                    # The regenerate just rebuilt this exact batch on the
                    # approved base revision, and the kernel bound it to the
                    # approval; the save refuses any other base revision under
                    # the repository's write lock. Until 2026-11-02 the commit
                    # replayed the batch (about 20 s on Factory 02). Checked
                    # again instead: what the save cannot see (recheck:
                    # artwork, component visuals, current catalog revisions,
                    # the referenced dependencies).
                    if recheck(service, principal, site_id, layout_id,
                               plan.binding.base_revision, operations, prepared,
                               undo=alternative["strategy"] == UNDO_TYPE
                               ) != plan.binding.dependency_fingerprint:
                        raise TransactionBindingError(
                            "transaction_binding_mismatch",
                            "Facility Layout changed during commit.",
                        )
                else:
                    # A generated layout is replayed as before: replaying its
                    # operations must preserve the exact approved content.
                    prepared, dependencies = service._prepare_operations(
                        principal, site_id, layout_id, plan.binding.base_revision,
                        operations, required_action="proposal.apply")
                    if (
                        prepared["diffHash"] != plan.binding.diff_hash
                        or canonical_layout_bytes(prepared["document"])
                        != canonical_layout_bytes(
                            alternative["ghostPreview"]["layout"]
                        )
                        or plan.recovery
                        != service._proposal_recovery_context(
                            alternative,
                            prepared,
                            dependencies,
                        )
                    ):
                        raise TransactionBindingError(
                            "transaction_binding_mismatch",
                            "Facility Layout changed during commit.",
                        )
                saved = service.layout_repository.save_approved_layout(
                    principal,
                    site_id,
                    layout_id,
                    prepared["document"],
                    plan.binding.base_revision,
                )
                commit_payload = (
                    deepcopy(dict(plan.recovery["commitPayload"])) if exact
                    else service._proposal_commit_payload(
                        alternative,
                        prepared,
                        dependencies,
                    )
                )
                return CommitResult(
                    revision=saved["revision"],
                    payload={
                        "changed": bool(saved.get("changed")),
                        **commit_payload,
                    },
                )

            def reconcile_prepared(
                self,
                prepared: PreparedRecord,
            ) -> ReconciliationResult:
                try:
                    current = service.layout_repository.get_layout(
                        principal,
                        site_id,
                        layout_id,
                    )
                except Exception:
                    return ReconciliationResult.unknown()
                recovery = prepared.recovery
                if (
                    recovery.get("schemaVersion") == 1
                    and recovery.get("kind")
                    == "facility-layout-commit"
                    and isinstance(
                        recovery.get("expectedLayout"),
                        Mapping,
                    )
                    and isinstance(
                        recovery.get("commitPayload"),
                        Mapping,
                    )
                    and isinstance(
                        recovery.get("expectedChanged"),
                        bool,
                    )
                ):
                    expected = deepcopy(
                        dict(recovery["expectedLayout"])
                    )
                    actual = deepcopy(dict(current["layout"]))
                    expected["createdAt"] = actual.get("createdAt")
                    expected["updatedAt"] = actual.get("updatedAt")
                    if (
                        canonical_layout_bytes(expected)
                        != canonical_layout_bytes(actual)
                    ):
                        if (
                            current["revision"]
                            == prepared.binding.base_revision
                        ):
                            return (
                                ReconciliationResult.not_committed()
                            )
                        return ReconciliationResult.unknown()
                    if (
                        current["revision"]
                        == prepared.binding.base_revision
                        and recovery["expectedChanged"]
                    ):
                        return ReconciliationResult.not_committed()
                    payload = deepcopy(
                        dict(recovery["commitPayload"])
                    )
                    payload["layout"] = actual
                    payload["changed"] = recovery["expectedChanged"]
                    return ReconciliationResult.committed(
                        CommitResult(
                            revision=current["revision"],
                            payload=payload,
                        )
                    )
                if (
                    recovery.get("schemaVersion") != 2
                    or recovery.get("kind") != "facility-layout-commit"
                    or not isinstance(
                        recovery.get("expectedLayoutFingerprint"),
                        str,
                    )
                    or len(recovery["expectedLayoutFingerprint"]) != 64
                    or not isinstance(
                        recovery.get("commitPayload"),
                        Mapping,
                    )
                    or not isinstance(
                        recovery.get("expectedChanged"),
                        bool,
                    )
                ):
                    if (
                        current["revision"]
                        == prepared.binding.base_revision
                    ):
                        return ReconciliationResult.not_committed()
                    return ReconciliationResult.unknown()

                actual = deepcopy(dict(current["layout"]))
                if (
                    service._layout_content_fingerprint(actual)
                    != recovery["expectedLayoutFingerprint"]
                ):
                    if (
                        current["revision"]
                        == prepared.binding.base_revision
                    ):
                        return ReconciliationResult.not_committed()
                    return ReconciliationResult.unknown()
                if (
                    current["revision"] == prepared.binding.base_revision
                    and recovery["expectedChanged"]
                ):
                    return ReconciliationResult.not_committed()

                payload = deepcopy(dict(recovery["commitPayload"]))
                payload["changed"] = recovery["expectedChanged"]
                return ReconciliationResult.committed(
                    CommitResult(
                        revision=current["revision"],
                        payload=payload,
                    )
                )

        try:
            outcome = self.transaction_runtime.apply(
                tenant_id=principal.tenant_id,
                site_id=site_id,
                layout_id=layout_id,
                approval_token=approval_token,
                binding=binding,
                principal_id=principal.principal_id,
                session_id=session_id,
                idempotency_key=idempotency_key,
                adapter=_FacilityApplyAdapter(),
            )
        except TransactionError as error:
            self._raise_transaction_error(error)
            raise AssertionError("unreachable")
        public_payload = self._hydrate_proposal_commit_payload(
            principal,
            site_id,
            layout_id,
            outcome.receipt.revision,
            outcome.receipt.payload,
        )
        return {
            **public_payload,
            "revision": outcome.receipt.revision,
            "receipt": outcome.receipt.to_dict(),
            "replayed": outcome.replayed,
            "recovered": outcome.recovered,
        }

    def get_layout_receipt(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        receipt_id: str,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="receipt.read",
        )
        try:
            receipt = self.transaction_runtime.kernel.get_receipt(receipt_id)
        except TransactionError as error:
            self._raise_transaction_error(error)
            raise AssertionError("unreachable")
        if receipt.binding.target != facility_transaction_target(
            tenant_id=principal.tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        ):
            raise FacilityNotFoundError(
                "receipt_not_found",
                "Facility Layout receipt was not found.",
            )
        return receipt.to_dict()

    def latest_layout_receipt(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
    ) -> dict[str, Any] | None:
        """The layout's newest receipt (its last saved change that has one), or None. Sage's
        show_facility_views uses it for "show me what you changed" when the app window has no receipt of its
        own (after a restart, or in a new window)."""
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="receipt.read",
        )
        store = self.transaction_runtime.kernel.receipt_store
        find = getattr(store, "latest_receipt_for", None)
        if find is None:
            return None
        receipt = find(facility_transaction_target(
            tenant_id=principal.tenant_id,
            site_id=site_id,
            layout_id=layout_id,
        ))
        return receipt.to_dict() if receipt is not None else None

    def _prepare_operations(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        operations: list[Mapping[str, Any]],
        *,
        required_action: str | None = "layout.edit",
        baseline_out: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], FacilityDependencySnapshot]:
        if required_action is not None:
            require_facility_action(
                principal,
                tenant_id=principal.tenant_id,
                site_id=site_id,
                action=required_action,
            )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        self._verify_spatial_candidate_operations(
            principal,
            site_id,
            current["layout"],
            base_revision,
            operations,
        )
        baseline_spatial = self._diagnose_spatial(
            principal,
            site_id,
            current["layout"],
        )
        baseline_routing = self._diagnose_routing(
            principal,
            site_id,
            current["layout"],
        )
        if baseline_out is not None:
            # The saved layout's diagnostics, for a caller that reports what
            # the change adds (operation_proposals).
            baseline_out.update(spatial=baseline_spatial, routing=baseline_routing)
        operation_result = apply_facility_layout_operations(
            current["layout"],
            operations,
            base_revision=base_revision,
        )
        dependencies = self.validate_dependencies(
            principal,
            site_id,
            operation_result["document"],
        )
        spatial = self._diagnose_spatial(
            principal,
            site_id,
            operation_result["document"],
        )
        self._require_no_new_spatial_errors(
            baseline_spatial,
            spatial,
            operations=operations,
            baseline_layout=current["layout"],
        )
        operation_result["spatialDiagnostics"] = spatial
        document, routing, rebound_ids = self._revalidate_route_layout_sources(
            principal,
            site_id,
            operation_result["document"],
            inherited_routes=(
                current["layout"]["routes"] if operation_result["changed"] else []
            ),
        )
        self._require_no_new_routing_errors(baseline_routing, routing)
        if rebound_ids:
            # The approval artifact must bind the revalidated route sources,
            # not just the caller's placement edits.
            diff = build_exact_layout_diff(current["layout"], document)
            operation_result.update(
                document=document,
                changed=bool(diff["changed"]),
                affectedIds=sorted(set(operation_result["affectedIds"]) | set(rebound_ids)),
                canonicalDiff=diff,
                diffHash=facility_layout_diff_hash(
                    layout_id=layout_id,
                    base_revision=base_revision,
                    operations=operations,
                    after=document,
                    canonical_diff=diff,
                ),
            )
        operation_result["routingDiagnostics"] = routing
        return operation_result, dependencies

    @staticmethod
    def _candidate_request(value: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(value, Mapping):
            raise FacilityValidationError(
                "invalid_spatial_request",
                "Spatial candidate request must be an object.",
            )
        forbidden = {
            "camera",
            "clientX",
            "clientY",
            "screen",
            "viewport",
            "zoom",
        }
        present = sorted(forbidden.intersection(value))
        if present:
            raise FacilityValidationError(
                "screen_coordinates_forbidden",
                "Spatial requests accept only Facility Layout world coordinates.",
                details={"forbiddenFields": present},
            )
        asset_id = value.get("assetId")
        revision = value.get("assetDefinitionRevision")
        position = value.get("requestedPosition")
        if not isinstance(asset_id, str) or not asset_id:
            raise FacilityValidationError(
                "invalid_spatial_request",
                "assetId is required.",
            )
        if not isinstance(revision, str) or len(revision) != 64:
            raise FacilityValidationError(
                "invalid_spatial_request",
                "assetDefinitionRevision must be a SHA-256 revision.",
            )
        if not isinstance(position, Mapping):
            raise FacilityValidationError(
                "invalid_spatial_request",
                "requestedPosition must be a world-coordinate object.",
            )
        families = value.get(
            "enabledFamilies",
            ["grid", "boundary", "row", "bay", "alignment", "foundation"],
        )
        if not isinstance(families, list) or not all(
            isinstance(item, str) for item in families
        ):
            raise FacilityValidationError(
                "invalid_spatial_request",
                "enabledFamilies must be an array of strings.",
            )
        maximum = value.get("maximumCandidates", 64)
        if (
            isinstance(maximum, bool)
            or not isinstance(maximum, int)
            or not 1 <= maximum <= 256
        ):
            raise FacilityValidationError(
                "invalid_spatial_request",
                "maximumCandidates must be between 1 and 256.",
            )
        quaternion = value.get("requestedQuaternion")
        if quaternion is not None and not isinstance(quaternion, Mapping):
            raise FacilityValidationError(
                "invalid_spatial_request",
                "requestedQuaternion must be an XYZW quaternion object.",
            )
        target = value.get("targetPlacementId")
        if target is not None and (
            not isinstance(target, str) or not target.startswith("pl-")
        ):
            raise FacilityValidationError(
                "invalid_spatial_request",
                "targetPlacementId must be a placement ID.",
            )
        position_mode = value.get("positionMode", "manual")
        if position_mode not in {"auto", "manual", "locked"}:
            raise FacilityValidationError(
                "invalid_spatial_request",
                "positionMode must be auto, manual, or locked.",
            )
        metadata = value.get("metadata", {})
        if not isinstance(metadata, Mapping):
            raise FacilityValidationError(
                "invalid_spatial_request",
                "metadata must be an object.",
            )
        return {
            "assetId": asset_id,
            "assetDefinitionRevision": revision,
            "requestedPosition": deepcopy(dict(position)),
            "enabledFamilies": list(families),
            "maximumCandidates": maximum,
            "requestedQuaternion": (
                None if quaternion is None else deepcopy(dict(quaternion))
            ),
            "targetPlacementId": target,
            "positionMode": position_mode,
            "metadata": deepcopy(dict(metadata)),
        }

    def _candidate_set_for_layout(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout: Mapping[str, Any],
        request: Mapping[str, Any],
    ) -> dict[str, Any]:
        normalized = self._candidate_request(request)
        context = self._spatial_context(
            principal,
            site_id,
            layout,
            additional_asset_refs=(
                (
                    normalized["assetId"],
                    normalized["assetDefinitionRevision"],
                ),
            ),
        )
        asset = context.asset_definitions[
            (
                normalized["assetId"],
                normalized["assetDefinitionRevision"],
            )
        ]
        return self.spatial_executor.run_candidates(
            layout,
            asset,
            normalized["requestedPosition"],
            context.asset_definitions,
            shell=context.shell,
            policy_set=context.policy_set,
            evidence_authority=context.evidence_authority,
            enabled_families=normalized["enabledFamilies"],
            requested_quaternion=normalized["requestedQuaternion"],
            target_placement_id=normalized["targetPlacementId"],
            asset_definition_revision=normalized[
                "assetDefinitionRevision"
            ],
            maximum_candidates=normalized["maximumCandidates"],
        )

    def generate_spatial_candidates(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.edit",
        )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        prior_operations = list(operations or [])
        self._verify_spatial_candidate_operations(
            principal,
            site_id,
            current["layout"],
            base_revision,
            prior_operations,
        )
        draft = apply_facility_layout_operations(
            current["layout"],
            prior_operations,
            base_revision=base_revision,
        )["document"]
        self.validate_dependencies(principal, site_id, draft)
        draft_spatial = self._diagnose_spatial(principal, site_id, draft)
        baseline_spatial = self._diagnose_spatial(
            principal,
            site_id,
            current["layout"],
        )
        self._require_no_new_spatial_errors(
            baseline_spatial,
            draft_spatial,
            operations=prior_operations,
            baseline_layout=current["layout"],
        )
        result = self._candidate_set_for_layout(
            principal,
            site_id,
            draft,
            request,
        )
        return {
            **result,
            "baseRevision": base_revision,
            "spatialDiagnostics": draft_spatial,
        }

    def layout_with_operations(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """The saved layout with the view's unsaved operations applied, for a read-only check such as the lighting
        coverage estimate. Nothing is stored."""
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        current = self.layout_repository.get_layout(principal, site_id, layout_id)
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        pending = list(operations or [])
        if not pending:
            return current["layout"]
        return apply_facility_layout_operations(
            current["layout"],
            pending,
            base_revision=base_revision,
        )["document"]

    def diagnose_spatial(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        pending = list(operations or [])
        self._verify_spatial_candidate_operations(
            principal,
            site_id,
            current["layout"],
            base_revision,
            pending,
        )
        draft = apply_facility_layout_operations(
            current["layout"],
            pending,
            base_revision=base_revision,
        )["document"]
        dependencies = self.validate_dependencies(principal, site_id, draft)
        diagnostics = self._diagnose_spatial(principal, site_id, draft)
        return {
            **diagnostics,
            "baseRevision": base_revision,
            "dependencies": dependencies.to_dict(),
        }

    def diagnose_routing(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        pending = list(operations or [])
        draft = apply_facility_layout_operations(
            current["layout"],
            pending,
            base_revision=base_revision,
        )["document"]
        dependencies = self.validate_dependencies(principal, site_id, draft)
        diagnostics = self._diagnose_routing(principal, site_id, draft)
        return {
            **diagnostics,
            "baseRevision": base_revision,
            "dependencies": dependencies.to_dict(),
        }

    def connector_candidates(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.edit",
        )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        pending = list(operations or [])
        draft = apply_facility_layout_operations(
            current["layout"],
            pending,
            base_revision=base_revision,
        )["document"]
        self.validate_dependencies(principal, site_id, draft)
        endpoint = request.get("sourceEndpoint")
        route_kind = request.get("routeKind")
        if not isinstance(endpoint, Mapping) or not isinstance(route_kind, str):
            raise FacilityValidationError(
                "invalid_route_request",
                "sourceEndpoint and routeKind are required.",
            )
        context = self._spatial_context(principal, site_id, draft)
        result = generate_connector_candidates(
            draft,
            endpoint,
            route_kind=route_kind,
            asset_definitions=context.asset_definitions,
            shell={
                "document": context.shell,
                "revision": draft["sourceShellRef"]["shellRevision"],
            },
            shell_revision=draft["sourceShellRef"]["shellRevision"],
            maximum_distance_meters=request.get("maximumDistanceMeters"),
            maximum_candidates=request.get("maximumCandidates", 64),
        )
        return {
            **result,
            "baseRevision": base_revision,
        }

    def plan_forklift_route(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.edit",
        )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        pending = list(operations or [])
        draft = apply_facility_layout_operations(
            current["layout"],
            pending,
            base_revision=base_revision,
        )["document"]
        self.validate_dependencies(principal, site_id, draft)
        source_endpoint = request.get("sourceEndpoint")
        target_endpoint = request.get("targetEndpoint")
        vehicle_ref = request.get("vehicleProfileRef")
        if (
            not isinstance(source_endpoint, Mapping)
            or not isinstance(target_endpoint, Mapping)
            or not isinstance(vehicle_ref, Mapping)
        ):
            raise FacilityValidationError(
                "invalid_route_request",
                "Source, target, and vehicle profile references are required.",
            )
        context = self._spatial_context(principal, site_id, draft)
        endpoint_kwargs = {
            "asset_definitions": context.asset_definitions,
            "shell": {
                "document": context.shell,
                "revision": draft["sourceShellRef"]["shellRevision"],
            },
            "shell_revision": draft["sourceShellRef"]["shellRevision"],
            "route_kind": "forklift",
        }
        source = resolve_endpoint(
            draft,
            source_endpoint,
            direction="source",
            **endpoint_kwargs,
        )
        target = resolve_endpoint(
            draft,
            target_endpoint,
            direction="target",
            **endpoint_kwargs,
        )
        endpoint_findings = [
            *source.get("findings", []),
            *target.get("findings", []),
        ]
        if not source.get("resolved") or not target.get("resolved"):
            return {
                "accepted": False,
                "baseRevision": base_revision,
                "findings": endpoint_findings,
                "processSemantics": {
                    "precedenceDerived": False,
                    "policy": (
                        "spatial_proximity_never_implies_process_precedence"
                    ),
                },
            }
        vehicle_id = str(vehicle_ref.get("vehicleProfileId") or "")
        vehicle_revision = str(
            vehicle_ref.get("vehicleProfileRevision") or ""
        )
        envelope = self.vehicle_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=vehicle_id,
            revision=vehicle_revision,
        )
        requested_zone_ids = request.get("traversableZoneIds")
        if requested_zone_ids is not None and (
            not isinstance(requested_zone_ids, list)
            or not all(isinstance(item, str) for item in requested_zone_ids)
        ):
            raise FacilityValidationError(
                "invalid_route_request",
                "traversableZoneIds must be an array of stable IDs.",
            )
        allowed_ids = (
            None if requested_zone_ids is None else set(requested_zone_ids)
        )
        traversable = [
            deepcopy(zone["boundary"])
            for zone in draft.get("zones", [])
            if isinstance(zone, Mapping)
            and zone.get("zoneType") == "aisle"
            and (allowed_ids is None or zone.get("zoneId") in allowed_ids)
        ]
        excluded = {
            str(endpoint.get("placementId"))
            for endpoint in (source_endpoint, target_endpoint)
            if endpoint.get("kind") == "placement_connector"
        }
        start_facing = source["facing"]
        target_facing = target["facing"]
        start = {
            **deepcopy(source["position"]),
            "heading": math.atan2(
                float(start_facing["z"]),
                float(start_facing["x"]),
            ),
        }
        goal = {
            **deepcopy(target["position"]),
            "heading": math.atan2(
                -float(target_facing["z"]),
                -float(target_facing["x"]),
            ),
        }
        result = plan_forklift_route(
            start,
            goal,
            envelope.document,
            traversable_polygons=traversable,
            obstacles=self._route_obstacles(
                draft,
                context.asset_definitions,
                context.shell,
                excluded_placement_ids=excluded,
            ),
            load=(
                request.get("load")
                if isinstance(request.get("load"), Mapping)
                else None
            ),
            allow_reverse=request.get("allowReverse"),
            grid_resolution_meters=request.get(
                "gridResolutionMeters",
                0.5,
            ),
            source_revisions={
                "layout": base_revision,
                "shell": draft["sourceShellRef"]["shellRevision"],
                "policy": draft["policySetRef"]["policySetRevision"],
                "vehicle": vehicle_revision,
            },
        )
        return {
            **result,
            "baseRevision": base_revision,
            "sourceEndpoint": deepcopy(dict(source_endpoint)),
            "targetEndpoint": deepcopy(dict(target_endpoint)),
            "vehicleProfileRef": {
                "vehicleProfileId": vehicle_id,
                "vehicleProfileRevision": vehicle_revision,
            },
        }

    def validate_manual_navigation_path(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Validate one Plan-authored path without mutating the draft."""

        self._require_capability("navigation_manual")
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.edit",
        )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        allowed_fields = {
            "actorPlacementId",
            "actorClass",
            "actorProfileRef",
            "constraintMode",
            "direction",
            "points",
            "prototypeMode",
        }
        unknown_fields = sorted(set(request) - allowed_fields)
        if unknown_fields:
            raise FacilityValidationError(
                "facility_navigation_manual_validation_unknown_field",
                "Manual navigation validation received unsupported fields.",
                details={"unknownFields": unknown_fields},
            )
        pending = list(operations or [])
        draft = apply_facility_layout_operations(
            current["layout"],
            pending,
            base_revision=base_revision,
        )["document"]
        self.validate_dependencies(principal, site_id, draft)

        placement_id = str(request.get("actorPlacementId") or "")
        actor_class = str(request.get("actorClass") or "")
        placement = next(
            (
                item
                for item in draft.get("placements", [])
                if isinstance(item, Mapping)
                and item.get("placementId") == placement_id
            ),
            None,
        )
        if placement is None:
            raise FacilityValidationError(
                "facility_navigation_actor_unavailable",
                "The selected navigation actor does not exist in this revision.",
                details={"actorPlacementId": placement_id},
            )
        context = self._spatial_context(principal, site_id, draft)
        asset_key = (
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        asset_definition = context.asset_definitions.get(asset_key)
        if asset_definition is None:
            raise FacilityValidationError(
                "facility_navigation_actor_geometry_unavailable",
                "The selected actor's exact catalog definition is unavailable.",
                details={"actorPlacementId": placement_id},
            )
        actor_type = self._prototype_actor_type(placement, asset_definition)
        expected_class = (
            "pedestrian" if actor_type == "operator"
            else "vehicle" if actor_type in {"vehicle", "mobile_equipment"}
            else None
        )
        if expected_class is None or actor_class != expected_class:
            raise FacilityValidationError(
                "facility_navigation_actor_class_mismatch",
                "The selected placement is not an actor of the requested class.",
                details={
                    "actorPlacementId": placement_id,
                    "requestedActorClass": actor_class,
                    "detectedActorType": actor_type,
                },
            )
        direction = str(request.get("direction") or "forward")
        if direction not in {"forward", "reverse", "bidirectional"}:
            raise FacilityValidationError(
                "facility_navigation_direction_invalid",
                "Manual navigation direction must use the closed navigation vocabulary.",
            )
        constraint_mode = str(request.get("constraintMode") or "")
        if constraint_mode not in {
            "guide",
            "locked_segment",
            "complete_override",
            "avoid_region",
            "preferred_corridor",
        }:
            raise FacilityValidationError(
                "facility_navigation_constraint_mode_invalid",
                "Manual navigation constraint mode is invalid.",
            )

        vehicle_profile = None
        profile_ref = request.get("actorProfileRef")
        if actor_class == "vehicle":
            if not isinstance(profile_ref, Mapping):
                raise FacilityValidationError(
                    "facility_navigation_vehicle_profile_unavailable",
                    "Vehicle path validation requires an exact published profile revision.",
                )
            profile_id = str(profile_ref.get("profileId") or "")
            profile_revision = str(profile_ref.get("profileRevision") or "")
            prototype_fallback = False
            try:
                envelope = self.vehicle_repository.get_published(
                    principal,
                    site_id=site_id,
                    authority_id=profile_id,
                    revision=profile_revision,
                )
            except FacilityNotFoundError:
                if (
                    not self.allow_prototype_motion
                    or request.get("prototypeMode") is not True
                ):
                    raise
                envelope = self.vehicle_repository.get_revision(
                    principal,
                    site_id=site_id,
                    authority_id=profile_id,
                    revision=profile_revision,
                )
                prototype_fallback = True
            if prototype_fallback and (
                envelope.document.get("prototypeMode") is not True
                or envelope.document.get("productionEligible") is not False
            ):
                raise FacilityValidationError(
                    "facility_navigation_prototype_profile_disabled",
                    "Prototype vehicle path validation requires an explicitly "
                    "enabled, non-production prototype profile.",
                    details={"vehicleProfileId": profile_id},
                )
            vehicle_profile = envelope.document
        elif profile_ref is not None:
            if not isinstance(profile_ref, Mapping) or (
                str(profile_ref.get("profileId") or "")
                != f"pedestrian-profile:{asset_key[0]}"
                or str(profile_ref.get("profileRevision") or "")
                != asset_key[1]
            ):
                raise FacilityValidationError(
                    "facility_navigation_actor_profile_mismatch",
                    "The pedestrian profile must bind to the selected catalog revision.",
                )

        result = validate_manual_navigation_path(
            points=request.get("points", []),
            actor_class=actor_class,
            actor_asset_definition=asset_definition,
            shell=context.shell,
            obstacles=self._route_obstacles(
                draft,
                context.asset_definitions,
                context.shell,
                excluded_placement_ids={placement_id},
            ),
            direction=("reverse" if direction == "reverse" else "forward"),
            vehicle_profile=vehicle_profile,
        )
        if actor_class == "vehicle" and prototype_fallback:
            result = {
                **result,
                "prototypeMode": True,
                "prototypeLabel": str(
                    envelope.document.get("prototypeLabel")
                    or "Explicit non-production vehicle profile"
                ),
                "productionEligible": False,
                "qualification": (
                    "Prototype profile operating limits are synthetic and not "
                    "production eligible. " + str(result["qualification"])
                ),
            }
        return {
            **result,
            "baseRevision": base_revision,
            "actorPlacementId": placement_id,
            "actorProfileRef": (
                deepcopy(dict(profile_ref))
                if isinstance(profile_ref, Mapping)
                else {
                    "profileKind": "pedestrian",
                    "profileId": f"pedestrian-profile:{asset_key[0]}",
                    "profileRevision": asset_key[1],
                }
            ),
            "constraintMode": constraint_mode,
            "mutated": False,
        }

    @staticmethod
    def _navigation_radius_from_points(
        points: Any,
        *,
        code: str,
    ) -> float:
        if not isinstance(points, list):
            raise FacilityValidationError(
                code,
                "The exact actor footprint is unavailable.",
            )
        vertices = []
        for raw in points:
            if not isinstance(raw, Mapping):
                continue
            try:
                x = float(raw["x"])
                z = float(raw["z"])
            except (KeyError, TypeError, ValueError):
                continue
            if math.isfinite(x) and math.isfinite(z):
                vertices.append((x, z))
        if len(vertices) < 3:
            raise FacilityValidationError(
                code,
                "The exact actor footprint is unavailable.",
            )
        return max(math.hypot(x, z) for x, z in vertices)

    @classmethod
    def _pedestrian_navigation_radius(
        cls,
        definition: Mapping[str, Any],
    ) -> float:
        geometry = definition.get("geometry")
        polygons = (
            geometry.get("footprintPolygons")
            if isinstance(geometry, Mapping)
            else None
        )
        points = polygons[0] if isinstance(polygons, list) and polygons else None
        return cls._navigation_radius_from_points(
            points,
            code="facility_navigation_actor_geometry_unavailable",
        )

    @classmethod
    def _vehicle_navigation_radius(
        cls,
        profile: Mapping[str, Any],
    ) -> float:
        return cls._navigation_radius_from_points(
            profile.get("footprint"),
            code="facility_navigation_vehicle_profile_unavailable",
        )

    def _resolve_navigation_draft(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        operations: list[Mapping[str, Any]] | None,
        trusted_draft: Mapping[str, Any] | None,
    ) -> dict[str, Any]:
        """Resolve a public operation batch or an internally trusted draft."""

        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        if trusted_draft is None:
            draft = apply_facility_layout_operations(
                current["layout"],
                list(operations or []),
                base_revision=base_revision,
            )["document"]
        else:
            if operations:
                raise FacilityValidationError(
                    "facility_navigation_draft_source_conflict",
                    "A trusted navigation draft cannot be combined with a public operation batch.",
                )
            draft = canonicalize_layout(deepcopy(dict(trusted_draft)))
            if (
                str(draft.get("siteId") or "") != site_id
                or str(draft.get("layoutId") or "") != layout_id
            ):
                raise FacilityValidationError(
                    "facility_navigation_draft_scope_mismatch",
                    "The trusted navigation draft belongs to another layout scope.",
                )
        self.validate_dependencies(principal, site_id, draft)
        return draft

    def compile_navigation_snapshot(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
        _trusted_draft: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Compile one immutable snapshot and return only a bounded summary."""

        self._require_capability("navigation_snapshot")
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        allowed = {
            "movementProgramId",
            "actorPlacementId",
            "actorClass",
            "actorProfileRef",
            "prototypeMode",
        }
        unknown = sorted(set(request) - allowed)
        if unknown:
            raise FacilityValidationError(
                "facility_navigation_snapshot_unknown_field",
                "Navigation snapshot request received unsupported fields.",
                details={"unknownFields": unknown},
            )
        draft = self._resolve_navigation_draft(
            principal,
            site_id,
            layout_id,
            base_revision,
            operations,
            _trusted_draft,
        )
        active_revision = layout_revision(draft)
        extension = (
            draft.get("extensions", {}).get("facilityNavigation", {})
            if isinstance(draft.get("extensions"), Mapping)
            else {}
        )
        movement_program_id = str(request.get("movementProgramId") or "")
        program = None
        if movement_program_id:
            program = next(
                (
                    item
                    for item in extension.get("movementPrograms", [])
                    if isinstance(item, Mapping)
                    and item.get("movementProgramId") == movement_program_id
                ),
                None,
            )
            if program is None:
                raise FacilityValidationError(
                    "facility_navigation_program_unavailable",
                    "The requested movement program does not exist in this draft.",
                    details={"movementProgramId": movement_program_id},
                )
        actor_placement_id = str(
            (program or {}).get("actorPlacementId")
            or request.get("actorPlacementId")
            or ""
        )
        actor_class = str(
            (program or {}).get("actorClass")
            or request.get("actorClass")
            or ""
        )
        profile_ref = (
            (program or {}).get("actorProfileRef")
            or request.get("actorProfileRef")
        )
        if program is not None:
            conflicting = {
                "actorPlacementId": actor_placement_id,
                "actorClass": actor_class,
                "actorProfileRef": profile_ref,
            }
            for field, expected in conflicting.items():
                if field in request and request[field] != expected:
                    raise FacilityValidationError(
                        "facility_navigation_program_binding_conflict",
                        "The request conflicts with the authored movement program.",
                        details={"field": field, "movementProgramId": movement_program_id},
                    )
        if actor_class not in {"pedestrian", "vehicle"}:
            raise FacilityValidationError(
                "facility_navigation_actor_class_invalid",
                "Navigation snapshot requires an exact pedestrian or vehicle actor.",
            )
        placement = next(
            (
                item
                for item in draft.get("placements", [])
                if isinstance(item, Mapping)
                and item.get("placementId") == actor_placement_id
            ),
            None,
        )
        if placement is None:
            raise FacilityValidationError(
                "facility_navigation_actor_unavailable",
                "The requested movement actor does not exist in this draft.",
                details={"actorPlacementId": actor_placement_id},
            )
        context = self._spatial_context(principal, site_id, draft)
        asset_key = (
            str(placement.get("assetId") or ""),
            str(placement.get("assetDefinitionRevision") or ""),
        )
        definition = context.asset_definitions.get(asset_key)
        if definition is None:
            raise FacilityValidationError(
                "facility_navigation_actor_geometry_unavailable",
                "The movement actor's exact catalog definition is unavailable.",
            )
        detected = self._prototype_actor_type(placement, definition)
        expected_class = (
            "pedestrian" if detected == "operator" else
            "vehicle" if detected in {"vehicle", "mobile_equipment"} else None
        )
        if actor_class != expected_class:
            raise FacilityValidationError(
                "facility_navigation_actor_class_mismatch",
                "The selected placement does not match the requested actor class.",
                details={"detectedActorType": detected},
            )
        if not isinstance(profile_ref, Mapping):
            raise FacilityValidationError(
                "facility_navigation_actor_profile_unavailable",
                "Navigation compilation requires an exact actor profile revision.",
            )
        profile_revision = str(profile_ref.get("profileRevision") or "")
        prototype_profile = False
        if actor_class == "pedestrian":
            if profile_revision != asset_key[1]:
                raise FacilityValidationError(
                    "facility_navigation_actor_profile_mismatch",
                    "The pedestrian profile must bind to the selected catalog revision.",
                )
            navigation_radius = self._pedestrian_navigation_radius(definition)
        else:
            profile_id = str(profile_ref.get("profileId") or "")
            try:
                profile_envelope = self.vehicle_repository.get_published(
                    principal,
                    site_id=site_id,
                    authority_id=profile_id,
                    revision=profile_revision,
                )
            except FacilityNotFoundError:
                if (
                    not self.allow_prototype_motion
                    or request.get("prototypeMode") is not True
                ):
                    raise
                profile_envelope = self.vehicle_repository.get_revision(
                    principal,
                    site_id=site_id,
                    authority_id=profile_id,
                    revision=profile_revision,
                )
                prototype_profile = True
            profile = profile_envelope.document
            if prototype_profile and (
                profile.get("prototypeMode") is not True
                or profile.get("productionEligible") is not False
            ):
                raise FacilityValidationError(
                    "facility_navigation_prototype_profile_disabled",
                    "Prototype navigation requires an explicit non-production profile.",
                )
            navigation_radius = self._vehicle_navigation_radius(profile)
        required_anchor_ids = (
            list(program.get("requiredAnchorIds", []))
            if isinstance(program, Mapping)
            else None
        )
        required_scope_points: list[dict[str, Any]] = []
        if isinstance(program, Mapping):
            selected_constraint_ids = set(
                str(item)
                for item in program.get("manualPathConstraintIds", [])
            )
            for constraint in extension.get("manualPathConstraints", []):
                if (
                    not isinstance(constraint, Mapping)
                    or str(constraint.get("manualPathConstraintId") or "")
                    not in selected_constraint_ids
                    or constraint.get("constraintMode")
                    not in {
                        "complete_override",
                        "guide",
                        "locked_segment",
                        "preferred_corridor",
                    }
                ):
                    continue
                required_scope_points.extend(
                    deepcopy(point)
                    for point in constraint.get("authoredPolyline", [])
                    if isinstance(point, Mapping)
                )
        forbidden_zone_ids = (
            list(program.get("forbiddenZoneIds", []))
            if isinstance(program, Mapping)
            else None
        )
        package = compile_navigation_snapshot_package(
            draft,
            shell=context.shell,
            asset_definitions=context.asset_definitions,
            actor_class=actor_class,
            actor_profile_revision=profile_revision,
            navigation_radius_meters=navigation_radius,
            shell_revision=str(draft["sourceShellRef"]["shellRevision"]),
            policy_revision=str(draft["policySetRef"]["policySetRevision"]),
            evidence_authority=context.evidence_authority,
            required_anchor_ids=required_anchor_ids,
            required_scope_points=required_scope_points,
            forbidden_zone_ids=forbidden_zone_ids,
        )
        self.navigation_snapshot_store.put(package)
        package_id = str(package["navigationPackageId"])
        with self._navigation_snapshot_owner_lock:
            self._navigation_snapshot_owners[package_id] = (
                principal.tenant_id,
                site_id,
                layout_id,
            )
        return {
            "baseRevision": base_revision,
            "activeDraftRevision": active_revision,
            "movementProgramId": movement_program_id or None,
            "actorPlacementId": actor_placement_id,
            "prototypeMode": prototype_profile,
            "productionEligible": False if prototype_profile else None,
            "summary": navigation_snapshot_summary(package),
            "mutated": False,
        }

    def get_navigation_snapshot_package(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        package_id: str,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        owner = (principal.tenant_id, site_id, layout_id)
        with self._navigation_snapshot_owner_lock:
            if self._navigation_snapshot_owners.get(package_id) != owner:
                raise FacilityNotFoundError(
                    "facility_navigation_package_unavailable",
                    "The requested navigation package is unavailable.",
                )
        return self.navigation_snapshot_store.get(package_id)

    def plan_actor_journey(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
        _trusted_draft: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Plan one actor against an owner-bound immutable snapshot."""

        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        allowed = {
            "navigationPackageId",
            "movementProgramId",
            "load",
            "allowReverse",
            "prototypeMode",
        }
        unknown = sorted(set(request) - allowed)
        if unknown:
            raise FacilityValidationError(
                "facility_navigation_journey_unknown_field",
                "Journey requests accept semantic identities and bounded policy only.",
                details={"unknownFields": unknown},
            )
        package_id = str(request.get("navigationPackageId") or "")
        program_id = str(request.get("movementProgramId") or "")
        if not package_id or not program_id:
            raise FacilityValidationError(
                "facility_navigation_journey_request_invalid",
                "Journey planning requires snapshot and movement-program identities.",
            )
        package = self.get_navigation_snapshot_package(
            principal,
            site_id,
            layout_id,
            package_id,
        )
        draft = self._resolve_navigation_draft(
            principal,
            site_id,
            layout_id,
            base_revision,
            operations,
            _trusted_draft,
        )
        if layout_revision(draft) != package["snapshot"]["layoutRevision"]:
            raise FacilityConflictError(
                "facility_navigation_snapshot_stale",
                "The navigation snapshot does not match the active draft geometry.",
            )
        navigation = draft.get("extensions", {}).get("facilityNavigation", {})
        program = next(
            (
                item
                for item in navigation.get("movementPrograms", [])
                if isinstance(item, Mapping)
                and item.get("movementProgramId") == program_id
            ),
            None,
        )
        if program is None:
            raise FacilityValidationError(
                "facility_navigation_program_unavailable",
                "The requested movement program does not exist in this draft.",
            )
        self._require_capability(
            "navigation_pedestrian"
            if program.get("actorClass") == "pedestrian"
            else "navigation_vehicle"
        )
        if program.get("actorClass") == "pedestrian":
            journey = plan_pedestrian_journey(draft, package, program_id)
            prototype = False
        else:
            profile_ref = program.get("actorProfileRef")
            if not isinstance(profile_ref, Mapping):
                raise FacilityValidationError(
                    "facility_navigation_vehicle_profile_unavailable",
                    "The vehicle program has no exact profile revision.",
                )
            profile_id = str(profile_ref.get("profileId") or "")
            profile_revision = str(profile_ref.get("profileRevision") or "")
            prototype = False
            try:
                envelope = self.vehicle_repository.get_published(
                    principal,
                    site_id=site_id,
                    authority_id=profile_id,
                    revision=profile_revision,
                )
            except FacilityNotFoundError:
                if (
                    not self.allow_prototype_motion
                    or request.get("prototypeMode") is not True
                ):
                    raise
                envelope = self.vehicle_repository.get_revision(
                    principal,
                    site_id=site_id,
                    authority_id=profile_id,
                    revision=profile_revision,
                )
                prototype = True
            profile = deepcopy(envelope.document)
            profile["vehicleProfileRevision"] = envelope.revision
            if prototype and (
                profile.get("prototypeMode") is not True
                or profile.get("productionEligible") is not False
            ):
                raise FacilityValidationError(
                    "facility_navigation_prototype_profile_disabled",
                    "Prototype navigation requires an explicit non-production profile.",
                )
            journey = plan_vehicle_journey(
                draft,
                package,
                program_id,
                vehicle_profile=profile,
                load=(
                    deepcopy(request["load"])
                    if isinstance(request.get("load"), Mapping)
                    else None
                ),
                allow_reverse=(
                    request.get("allowReverse")
                    if isinstance(request.get("allowReverse"), bool)
                    else None
                ),
            )
        self.journey_solution_store.put(journey)
        journey_id = str(journey["journeySolutionId"])
        with self._journey_solution_owner_lock:
            self._journey_solution_owners[journey_id] = (
                principal.tenant_id,
                site_id,
                layout_id,
            )
        return {
            "baseRevision": base_revision,
            "activeDraftRevision": layout_revision(draft),
            "navigationPackageId": package_id,
            "prototypeMode": prototype,
            "productionEligible": False if prototype else None,
            "summary": journey_solution_summary(journey),
            "mutated": False,
        }

    def get_actor_journey(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        journey_solution_id: str,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        owner = (principal.tenant_id, site_id, layout_id)
        with self._journey_solution_owner_lock:
            if self._journey_solution_owners.get(journey_solution_id) != owner:
                raise FacilityNotFoundError(
                    "facility_navigation_journey_unavailable",
                    "The requested journey solution is unavailable.",
                )
        return self.journey_solution_store.get(journey_solution_id)

    def compile_navigation_handoff(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Compile one read-only handoff from owner-bound actor journeys."""

        self._require_capability("navigation_handoff")
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        allowed = {"handoffProgramId", "journeySolutionIds"}
        unknown = sorted(set(request) - allowed)
        if unknown:
            raise FacilityValidationError(
                "facility_navigation_handoff_unknown_field",
                "Handoff requests accept only stable program and journey identities.",
                details={"unknownFields": unknown},
            )
        handoff_program_id = str(request.get("handoffProgramId") or "")
        journey_ids = request.get("journeySolutionIds")
        if (
            not handoff_program_id
            or not isinstance(journey_ids, list)
            or len(journey_ids) != 2
            or any(not isinstance(item, str) or not item for item in journey_ids)
            or len(set(journey_ids)) != 2
        ):
            raise FacilityValidationError(
                "facility_navigation_handoff_request_invalid",
                "Handoff compilation requires one program and two distinct journey identities.",
            )
        current = self.layout_repository.get_layout(principal, site_id, layout_id)
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        draft = apply_facility_layout_operations(
            current["layout"],
            list(operations or []),
            base_revision=base_revision,
        )["document"]
        self.validate_dependencies(principal, site_id, draft)
        active_revision = layout_revision(draft)
        journeys = [
            self.get_actor_journey(
                principal,
                site_id,
                layout_id,
                journey_solution_id,
            )
            for journey_solution_id in journey_ids
        ]
        for journey in journeys:
            if journey["layoutRevision"] != active_revision:
                raise FacilityConflictError(
                    "facility_navigation_journey_stale",
                    "A handoff journey does not match the active draft geometry.",
                )
        result = compile_handoff_topology(draft, handoff_program_id, journeys)
        self.navigation_handoff_store.put(result)
        result_id = str(result["handoffResultId"])
        with self._navigation_handoff_owner_lock:
            self._navigation_handoff_owners[result_id] = (
                principal.tenant_id,
                site_id,
                layout_id,
            )
        return {
            "baseRevision": base_revision,
            "activeDraftRevision": active_revision,
            "summary": handoff_topology_summary(result),
            "mutated": False,
        }

    def get_navigation_handoff(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        handoff_result_id: str,
    ) -> dict[str, Any]:
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        owner = (principal.tenant_id, site_id, layout_id)
        with self._navigation_handoff_owner_lock:
            if self._navigation_handoff_owners.get(handoff_result_id) != owner:
                raise FacilityNotFoundError(
                    "facility_navigation_handoff_result_unavailable",
                    "The requested handoff result is unavailable.",
                )
        return self.navigation_handoff_store.get(handoff_result_id)

    @staticmethod
    def _navigation_actor_display_profile(
        placement: Mapping[str, Any],
        asset_definition: Mapping[str, Any],
        profile_ref: Mapping[str, Any],
    ) -> dict[str, Any]:
        geometry = asset_definition.get("geometry")
        footprint_polygons = (
            geometry.get("footprintPolygons")
            if isinstance(geometry, Mapping)
            else None
        )
        aabb = geometry.get("aabb") if isinstance(geometry, Mapping) else None
        if (
            not isinstance(footprint_polygons, list)
            or not footprint_polygons
            or not isinstance(footprint_polygons[0], list)
            or len(footprint_polygons[0]) < 3
        ):
            raise FacilityValidationError(
                "facility_navigation_actor_geometry_unavailable",
                "Navigation playback requires the exact catalog actor footprint.",
            )
        scale_value = placement.get("transform", {}).get("scale", 1)
        scale = float(scale_value) if isinstance(scale_value, (int, float)) else 1.0
        if not math.isfinite(scale) or scale <= 0:
            raise FacilityValidationError(
                "facility_navigation_actor_geometry_unavailable",
                "Navigation playback requires a positive finite actor scale.",
            )
        footprint = footprint_polygons[0]
        if (
            isinstance(aabb, Mapping)
            and isinstance(aabb.get("minimum"), Mapping)
            and isinstance(aabb.get("maximum"), Mapping)
        ):
            minimum = aabb["minimum"]
            maximum = aabb["maximum"]
        else:
            height = geometry.get("heightInterval", {})
            minimum = {
                "x": min(float(point["x"]) for point in footprint),
                "y": float(height.get("minimumY", 0)),
                "z": min(float(point["z"]) for point in footprint),
            }
            maximum = {
                "x": max(float(point["x"]) for point in footprint),
                "y": float(height.get("maximumY", 0)),
                "z": max(float(point["z"]) for point in footprint),
            }
        return {
            "profileKind": str(profile_ref["profileKind"]),
            "profileId": str(profile_ref["profileId"]),
            "profileRevision": str(profile_ref["profileRevision"]),
            "assetDefinitionRef": {
                "assetId": str(placement["assetId"]),
                "assetDefinitionRevision": str(
                    placement["assetDefinitionRevision"]
                ),
            },
            "footprint": [
                {
                    "x": round(float(point["x"]) * scale, 6),
                    "z": round(float(point["z"]) * scale, 6),
                }
                for point in footprint
            ],
            "overallDimensions": {
                "length": round(
                    (float(maximum["x"]) - float(minimum["x"])) * scale,
                    6,
                ),
                "width": round(
                    (float(maximum["z"]) - float(minimum["z"])) * scale,
                    6,
                ),
                "height": round(
                    (float(maximum["y"]) - float(minimum["y"])) * scale,
                    6,
                ),
            },
            "geometryAuthority": "catalog_revision_bound",
        }

    @staticmethod
    def _navigation_actor_department_ids(
        layout: Mapping[str, Any],
        placement: Mapping[str, Any],
    ) -> list[str]:
        position = placement.get("transform", {}).get("position", {})
        if not isinstance(position, Mapping):
            return []
        point = (float(position.get("x", 0)), float(position.get("z", 0)))
        result = []
        for zone in layout.get("zones", []):
            if not isinstance(zone, Mapping):
                continue
            boundary = zone.get("boundary")
            if not isinstance(boundary, list) or len(boundary) < 3:
                continue
            polygon = [
                (float(item["x"]), float(item["z"]))
                for item in boundary
                if isinstance(item, Mapping) and "x" in item and "z" in item
            ]
            if len(polygon) >= 3 and point_in_polygon(point, polygon):
                result.append(str(zone["zoneId"]))
        return sorted(set(result))

    def build_navigation_activity_scenario(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Assemble accepted journeys on one non-authoritative display clock."""

        self._require_capability("navigation_multi_actor")
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        allowed = {
            "journeySolutionIds",
            "handoffResultIds",
            "scenarioLabel",
            "prototypeMode",
        }
        unknown = sorted(set(request) - allowed)
        if unknown:
            raise FacilityValidationError(
                "facility_navigation_activity_unknown_field",
                "Navigation activity accepts identities and presentation labels only.",
                details={"unknownFields": unknown},
            )
        journey_ids = request.get("journeySolutionIds")
        if (
            request.get("prototypeMode") is not True
            or not isinstance(journey_ids, list)
            or not journey_ids
            or len(journey_ids) > FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS
            or any(not isinstance(item, str) or not item for item in journey_ids)
            or len(journey_ids) != len(set(journey_ids))
        ):
            raise FacilityValidationError(
                "facility_navigation_activity_request_invalid",
                f"Explicit prototype mode and 1-{FACILITY_NAVIGATION_ACTIVITY_MAXIMUM_ACTORS} unique accepted journey IDs are required.",
            )
        handoff_ids = request.get("handoffResultIds", [])
        if (
            not isinstance(handoff_ids, list)
            or any(not isinstance(item, str) or not item for item in handoff_ids)
            or len(handoff_ids) != len(set(handoff_ids))
        ):
            raise FacilityValidationError(
                "facility_navigation_activity_request_invalid",
                "handoffResultIds must contain unique stable identities.",
            )
        current = self.layout_repository.get_layout(principal, site_id, layout_id)
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        draft = apply_facility_layout_operations(
            current["layout"],
            list(operations or []),
            base_revision=base_revision,
        )["document"]
        self.validate_dependencies(principal, site_id, draft)
        active_revision = layout_revision(draft)
        journeys = [
            self.get_actor_journey(
                principal,
                site_id,
                layout_id,
                journey_solution_id,
            )
            for journey_solution_id in journey_ids
        ]
        if any(
            journey["outcome"] != "accepted"
            or journey["generationLayoutRevision"] != active_revision
            for journey in journeys
        ):
            raise FacilityConflictError(
                "facility_navigation_activity_journey_stale_or_unaccepted",
                "Every activity actor requires an accepted journey for the active draft.",
            )
        handoffs = [
            self.get_navigation_handoff(
                principal,
                site_id,
                layout_id,
                handoff_result_id,
            )
            for handoff_result_id in handoff_ids
        ]
        selected_journey_ids = set(journey_ids)
        for handoff in handoffs:
            participants = {
                handoff["sourceParticipant"]["journeySolutionId"],
                handoff["targetParticipant"]["journeySolutionId"],
            }
            if handoff["outcome"] != "complete" or not participants.issubset(
                selected_journey_ids
            ):
                raise FacilityValidationError(
                    "facility_navigation_activity_handoff_incomplete",
                    "Activity handoffs must be complete and bind selected journeys.",
                )
        navigation = draft.get("extensions", {}).get("facilityNavigation", {})
        programs = {
            str(item.get("movementProgramId")): item
            for item in navigation.get("movementPrograms", [])
            if isinstance(item, Mapping) and item.get("movementProgramId")
        }
        placements = {
            str(item.get("placementId")): item
            for item in draft.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        }
        context = self._spatial_context(principal, site_id, draft)
        actors = []
        actor_payloads: dict[str, dict[str, Any]] = {}
        maximum_duration = 0.0
        for index, journey in enumerate(journeys):
            program = programs.get(str(journey["movementProgramId"]))
            placement = placements.get(str(journey["actorPlacementId"]))
            if program is None or placement is None:
                raise FacilityValidationError(
                    "facility_navigation_activity_binding_unavailable",
                    "A journey no longer resolves to its movement program and actor.",
                )
            actor_class = str(program["actorClass"])
            profile_ref = program.get("actorProfileRef")
            if not isinstance(profile_ref, Mapping):
                raise FacilityValidationError(
                    "facility_navigation_actor_profile_unavailable",
                    "The movement program has no exact actor profile revision.",
                )
            asset_key = (
                str(placement["assetId"]),
                str(placement["assetDefinitionRevision"]),
            )
            definition = context.asset_definitions.get(asset_key)
            if definition is None:
                raise FacilityValidationError(
                    "facility_navigation_actor_geometry_unavailable",
                    "The exact catalog actor definition is unavailable.",
                )
            actor_profile = self._navigation_actor_display_profile(
                placement,
                definition,
                profile_ref,
            )
            built = build_navigation_journey_motion_package(
                journey,
                actor_class=actor_class,
                actor_profile_ref=profile_ref,
            )
            package = built["package"]
            package_id = str(package["packageId"])
            payload = {
                "package": deepcopy(package),
                "facilityMotionEnvelope": deepcopy(
                    built["facilityMotionEnvelope"]
                ),
                "actorProfile": actor_profile,
                "activeValidationContextFingerprint": journey[
                    "validationContextFingerprint"
                ],
                "prototypeMode": True,
            }
            actor_payloads[package_id] = payload
            self.motion_package_store.put(package_id, payload)
            duration = float(package["movement"]["presentationDurationSeconds"])
            maximum_duration = max(maximum_duration, duration)
            loop_mode = str(program["loopMode"])
            repeats = loop_mode != "one_way"
            placement_id = str(placement["placementId"])
            display_name = str(
                (placement.get("metadata") or {}).get("instanceLabel")
                or definition.get("displayName") or placement.get("assetId")
            )
            actors.append({
                "actorId": f"actor-nav-{index + 1:02d}-{placement_id[3:15]}",
                "actorType": "operator" if actor_class == "pedestrian" else "vehicle",
                "label": display_name,
                "motionPackageId": package_id,
                "returnMotionPackageId": None,
                "endTransferMotionPackageId": None,
                "startTransferMotionPackageId": None,
                "cycleMotionPackageIds": [],
                "placementId": placement_id,
                "assetDefinitionRef": {
                    "assetId": asset_key[0],
                    "assetDefinitionRevision": asset_key[1],
                },
                "routeId": str(program["movementProgramId"]),
                "departmentZoneIds": self._navigation_actor_department_ids(
                    draft,
                    placement,
                ),
                "startOffsetSeconds": 0,
                "repeat": repeats,
                "loopMode": "journey_cycle" if repeats else "once",
                "endpointTurnSeconds": 0,
                "visualAlignment": activity_visual_alignment({
                    "assetId": asset_key[0],
                    "assetDefinitionRevision": asset_key[1],
                }),
            })
        presentation = build_navigation_activity_presentation(
            actors,
            actor_payloads,
            cycle_duration_seconds=max(1.0, maximum_duration),
            handoff_result_ids=handoff_ids,
        )
        selected_placements = {actor["placementId"] for actor in actors}
        stationary_types = set()
        stationary_count = 0
        for placement in draft.get("placements", []):
            if not isinstance(placement, Mapping) or placement.get("placementId") in selected_placements:
                continue
            definition = context.asset_definitions.get((
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            ))
            category = str(definition.get("category") if isinstance(definition, Mapping) else "").casefold()
            if category in {"machines", "automation", "machine"}:
                stationary_count += 1
                stationary_types.add(str(placement.get("assetId") or ""))
        scenario = build_navigation_activity_scenario(
            layout_revision=active_revision,
            label=str(request.get("scenarioLabel") or "Navigation activity"),
            actors=actors,
            cycle_duration_seconds=max(1.0, maximum_duration),
            navigation_presentation=presentation,
            stationary_evidence={
                "placementCount": stationary_count,
                "assetTypeCount": len(stationary_types),
                "reason": (
                    "Fixed machinery remains stationary because no selected "
                    "placement has revision-bound machine kinematic evidence."
                ),
                "evidenceStatus": "unknown",
            },
        )
        scenario_id = str(scenario["scenarioId"])
        self.activity_scenario_store.put(
            scenario_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": active_revision,
                "scenario": scenario,
                "actorPayloads": actor_payloads,
            },
        )
        return {
            "scenarioId": scenario_id,
            "layoutRevision": active_revision,
            "summary": facility_activity_scenario_summary(scenario),
            "fullScenarioPath": (
                f"/api/facility-layouts/{site_id}/{layout_id}/"
                f"activity-scenarios/{scenario_id}"
            ),
            "mutated": False,
        }

    def build_forklift_motion_package(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Plan and cache one read-only playback package for an authored route."""

        pending = list(operations or [])
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.edit" if pending else "layout.read",
        )
        allowed_fields = {
            "routeId",
            "vehicleProfileRef",
            "vehiclePlacementId",
            "load",
            "allowReverse",
            "travelDirection",
        }
        unknown_fields = sorted(set(request) - allowed_fields)
        if unknown_fields:
            raise FacilityValidationError(
                "facility_motion_request_unknown_field",
                "Motion requests accept semantic route and vehicle identities only.",
                details={"unknownFields": unknown_fields},
            )
        route_id = str(request.get("routeId") or "")
        vehicle_ref = request.get("vehicleProfileRef")
        if not route_id or not isinstance(vehicle_ref, Mapping):
            raise FacilityValidationError(
                "facility_motion_request_invalid",
                "routeId and an exact vehicleProfileRef are required.",
            )
        vehicle_id = str(vehicle_ref.get("vehicleProfileId") or "")
        vehicle_revision = str(
            vehicle_ref.get("vehicleProfileRevision") or ""
        )
        if not vehicle_id or not vehicle_revision:
            raise FacilityValidationError(
                "facility_motion_request_invalid",
                "The exact vehicle-profile ID and revision are required.",
            )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        draft = apply_facility_layout_operations(
            current["layout"],
            pending,
            base_revision=base_revision,
        )["document"]
        self.validate_dependencies(principal, site_id, draft)
        active_revision = layout_revision(draft)
        route = next(
            (
                item
                for item in draft.get("routes", [])
                if isinstance(item, Mapping) and item.get("routeId") == route_id
            ),
            None,
        )
        if route is None:
            raise FacilityNotFoundError(
                "facility_motion_route_not_found",
                "The selected route is not present in this layout revision.",
                details={"routeId": route_id},
            )
        if route.get("routeKind") not in {"forklift", "material"}:
            raise FacilityValidationError(
                "facility_motion_route_not_vehicle_traversable",
                "Motion playback requires an authored vehicle route.",
                details={"routeId": route_id},
            )
        travel_direction = str(request.get("travelDirection") or "forward")
        if travel_direction not in {"forward", "reverse"}:
            raise FacilityValidationError(
                "facility_motion_request_invalid",
                "travelDirection must be forward or reverse.",
            )
        authored_direction = str(
            ((route.get("extensions") or {}).get("facilityAisle") or {}).get(
                "direction"
            )
            or "two_way"
        )
        if travel_direction == "reverse" and authored_direction == "one_way":
            raise FacilityValidationError(
                "facility_motion_route_direction_refused",
                "The authored one-way route cannot be replayed in reverse.",
                details={"routeId": route_id},
            )
        source_lane_binding = derive_directional_lane(
            draft,
            route,
            travel_direction=travel_direction,
        )
        prototype_fallback = False
        try:
            envelope = self.vehicle_repository.get_published(
                principal,
                site_id=site_id,
                authority_id=vehicle_id,
                revision=vehicle_revision,
            )
        except FacilityNotFoundError:
            if not self.allow_prototype_motion:
                raise
            envelope = self.vehicle_repository.get_revision(
                principal,
                site_id=site_id,
                authority_id=vehicle_id,
                revision=vehicle_revision,
            )
            prototype_fallback = True
        prototype_profile = envelope.document.get("prototypeMode") is True
        if (
            prototype_fallback and not prototype_profile
        ) or (
            prototype_profile
            and (
                envelope.document.get("productionEligible") is not False
                or not self.allow_prototype_motion
            )
        ):
            raise FacilityValidationError(
                "facility_motion_prototype_profile_disabled",
                "Prototype vehicle profiles require an explicitly enabled "
                "prototype-motion host and must be marked non-production.",
                details={"vehicleProfileId": vehicle_id},
            )
        footprint = envelope.document.get("footprint")
        longitudinal_extent = max(
            (
                abs(float(point.get("x", 0.0)))
                for point in footprint
                if isinstance(point, Mapping)
            ),
            default=0.0,
        ) if isinstance(footprint, list) else 0.0
        context = self._spatial_context(principal, site_id, draft)
        vehicle_placement_id = request.get("vehiclePlacementId")
        if vehicle_placement_id is not None and (
            not isinstance(vehicle_placement_id, str) or not vehicle_placement_id
        ):
            raise FacilityValidationError(
                "facility_motion_request_invalid",
                "vehiclePlacementId must be a stable layout identity.",
            )
        vehicle_placement = None
        if isinstance(vehicle_placement_id, str):
            vehicle_placement = next(
                (
                    item
                    for item in draft.get("placements", [])
                    if isinstance(item, Mapping)
                    and item.get("placementId") == vehicle_placement_id
                ),
                None,
            )
            if vehicle_placement is None:
                raise FacilityNotFoundError(
                    "facility_motion_vehicle_placement_not_found",
                    "The requested vehicle placement is not present in this "
                    "layout revision.",
                    details={"vehiclePlacementId": vehicle_placement_id},
                )
            asset_ref = envelope.document.get("assetDefinitionRef")
            if not isinstance(asset_ref, Mapping):
                raise FacilityValidationError(
                    "facility_motion_vehicle_asset_binding_required",
                    "A placed vehicle can move only when its exact asset "
                    "definition is bound to the vehicle profile.",
                    details={
                        "vehiclePlacementId": vehicle_placement_id,
                        "vehicleProfileId": vehicle_id,
                    },
                )
            expected_asset = {
                "assetId": str(asset_ref.get("assetId") or ""),
                "assetDefinitionRevision": str(
                    asset_ref.get("assetDefinitionRevision") or ""
                ),
            }
            actual_asset = {
                "assetId": str(vehicle_placement.get("assetId") or ""),
                "assetDefinitionRevision": str(
                    vehicle_placement.get("assetDefinitionRevision") or ""
                ),
            }
            if expected_asset != actual_asset:
                raise FacilityValidationError(
                    "facility_motion_vehicle_asset_binding_mismatch",
                    "The selected placement does not match the vehicle asset "
                    "definition bound to this profile revision.",
                    details={
                        "vehiclePlacementId": vehicle_placement_id,
                        "expectedAssetDefinitionRef": expected_asset,
                        "actualAssetDefinitionRef": actual_asset,
                    },
                )
        carried_ids = {
            str(item.get("placementId"))
            for item in draft.get("placements", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("snapRelationship"), Mapping)
            and item["snapRelationship"].get("supportPlacementId")
            == vehicle_placement_id
            and item.get("placementId")
        }
        excluded_ids = set(carried_ids)
        if isinstance(vehicle_placement_id, str):
            excluded_ids.add(vehicle_placement_id)
        lane_candidates = [source_lane_binding]
        adjusted_lane = inward_lane_binding_candidate(
            route,
            source_lane_binding,
            adjustment_meters=0.5,
        )
        if adjusted_lane is not None:
            lane_candidates.append(adjusted_lane)
        obstacles = self._route_obstacles(
            draft,
            context.asset_definitions,
            context.shell,
            excluded_placement_ids=excluded_ids,
        )
        result: dict[str, Any] = {}
        lane_binding = source_lane_binding
        for candidate_index, candidate_lane in enumerate(lane_candidates):
            centerline = inset_lane_endpoints(
                candidate_lane["laneCenterline"],
                longitudinal_extent + 0.5,
            )
            first, second = centerline[0], centerline[1]
            penultimate, last = centerline[-2], centerline[-1]
            try:
                start_heading = normalized_cardinal_route_heading(first, second)
                goal_heading = normalized_cardinal_route_heading(
                    penultimate,
                    last,
                )
            except ValueError as exc:
                raise FacilityValidationError(
                    "facility_motion_route_heading_unsupported",
                    str(exc),
                    details={"routeId": route_id},
                ) from exc
            result = plan_forklift_route(
                {
                    "x": float(first["x"]),
                    "y": float(first.get("y", 0.0)),
                    "z": float(first["z"]),
                    "heading": start_heading,
                },
                {
                    "x": float(last["x"]),
                    "y": float(last.get("y", 0.0)),
                    "z": float(last["z"]),
                    "heading": goal_heading,
                },
                envelope.document,
                traversable_polygons=route_traversable_corridor(route),
                obstacles=obstacles,
                load=(
                    request.get("load")
                    if isinstance(request.get("load"), Mapping)
                    else None
                ),
                allow_reverse=request.get("allowReverse"),
                grid_resolution_meters=0.5,
                source_revisions={
                    "layout": active_revision,
                    "shell": draft["sourceShellRef"]["shellRevision"],
                    "policy": draft["policySetRef"]["policySetRevision"],
                    "vehicle": vehicle_revision,
                },
            )
            lane_binding = candidate_lane
            finding_codes = {
                str(item.get("code") or "")
                for item in result.get("findings", [])
                if isinstance(item, Mapping)
            }
            can_try_inward = (
                candidate_index + 1 < len(lane_candidates)
                and result.get("accepted") is not True
                and finding_codes == {"route_width_insufficient"}
            )
            if not can_try_inward:
                break
        obstacle_context_revision = routing_layout_fingerprint(draft)
        profile_document = deepcopy(envelope.document)
        profile_document["vehicleProfileRevision"] = envelope.revision
        swept_volume = result.get("sweptVolume")
        influence_bounds = (
            swept_volume.get("sweptBounds")
            if isinstance(swept_volume, Mapping)
            else None
        )
        if not isinstance(influence_bounds, Mapping):
            centerline = [
                point
                for point in route.get("centerline", [])
                if isinstance(point, Mapping)
                and isinstance(point.get("x"), (int, float))
                and isinstance(point.get("z"), (int, float))
            ]
            if not centerline:
                raise FacilityValidationError(
                    "facility_motion_validation_context_unavailable",
                    "The selected route has no geometry for a validation context.",
                    details={"routeId": route_id},
                )
            half_width = max(0.0, float(route.get("corridorWidth") or 0.0) / 2.0)
            influence_bounds = {
                "minimum": {
                    "x": min(float(point["x"]) for point in centerline) - half_width,
                    "z": min(float(point["z"]) for point in centerline) - half_width,
                },
                "maximum": {
                    "x": max(float(point["x"]) for point in centerline) + half_width,
                    "z": max(float(point["z"]) for point in centerline) + half_width,
                },
            }
        planner_versions = {
            "routingEngineVersion": str(
                result.get("routingEngineVersion") or ROUTING_ENGINE_VERSION
            ),
            "routerVersion": str(result.get("routerVersion") or ROUTER_VERSION),
        }
        validation_context_spec = build_motion_validation_context_spec(
            draft,
            route_id=route_id,
            actor_profile_ref={
                "vehicleProfileId": vehicle_id,
                "vehicleProfileRevision": vehicle_revision,
            },
            planner_versions=planner_versions,
            influence_bounds=influence_bounds,
            actor_placement_id=vehicle_placement_id,
            marking_ids=lane_binding.get("sourceMarkingIds", []),
            additional_placement_ids=sorted(carried_ids),
            load_context=(
                request.get("load")
                if isinstance(request.get("load"), Mapping)
                else None
            ),
        )
        validation_context_projection = build_motion_validation_context_projection(
            draft,
            validation_context_spec,
            actor_profile=profile_document,
            obstacles=obstacles,
        )
        built = build_facility_motion_package_v2(
            result,
            layout=draft,
            layout_revision=active_revision,
            obstacle_context_revision=obstacle_context_revision,
            route_id=route_id,
            vehicle_profile_ref={
                "vehicleProfileId": vehicle_id,
                "vehicleProfileRevision": vehicle_revision,
            },
            validation_context_spec=validation_context_spec,
            validation_context_projection=validation_context_projection,
            vehicle_placement_id=vehicle_placement_id,
            lane_binding=lane_binding,
        )
        package_id = built["package"]["packageId"]
        self.motion_package_store.put(
            package_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": active_revision,
                "package": built["package"],
                "facilityMotionEnvelope": built["facilityMotionEnvelope"],
                "vehicleProfile": profile_document,
                "validationContextSpec": validation_context_spec,
                "validationContextProjection": validation_context_projection,
                "obstacleExcludedPlacementIds": sorted(excluded_ids),
            },
        )
        return {
            "packageId": package_id,
            "summary": built["summary"],
            "layoutRevision": active_revision,
            "canonicalBytes": built["canonicalBytes"],
            "fullPackagePath": (
                f"/api/facility-layouts/{site_id}/{layout_id}/motion-packages/"
                f"{package_id}"
            ),
        }

    def get_forklift_motion_package(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        package_id: str,
        *,
        active_revision: str | None = None,
    ) -> dict[str, Any]:
        """Fetch browser-only motion evidence with an exact revision gate."""

        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        payload = self.motion_package_store.get(package_id)
        if (
            payload.get("tenantId") != principal.tenant_id
            or payload.get("siteId") != site_id
            or payload.get("layoutId") != layout_id
        ):
            raise FacilityNotFoundError(
                "facility_motion_package_not_found",
                "The Facility Motion Package is unavailable in this context.",
            )
        package = payload.get("package")
        package_schema = (
            package.get("schemaVersion") if isinstance(package, Mapping) else None
        )
        expected_revision = str(payload.get("layoutRevision") or "")
        if active_revision is None:
            current = self.layout_repository.get_layout(
                principal,
                site_id,
                layout_id,
            )
            active_revision = str(current["revision"])
        active_validation_context_fingerprint = None
        if package_schema == FACILITY_MOTION_PACKAGE_SCHEMA_VERSION_V2:
            current = self.layout_repository.get_layout(
                principal,
                site_id,
                layout_id,
            )
            if current["revision"] == active_revision:
                current_layout = current["layout"]
                current_context = self._spatial_context(
                    principal,
                    site_id,
                    current_layout,
                )
                current_obstacles = self._route_obstacles(
                    current_layout,
                    current_context.asset_definitions,
                    current_context.shell,
                    excluded_placement_ids=set(
                        payload.get("obstacleExcludedPlacementIds") or []
                    ),
                )
                projection = build_motion_validation_context_projection(
                    current_layout,
                    payload["validationContextSpec"],
                    actor_profile=payload["vehicleProfile"],
                    obstacles=current_obstacles,
                )
                active_validation_context_fingerprint = (
                    motion_validation_context_fingerprint(projection)
                )
            elif active_revision == expected_revision:
                # The package was generated from the caller's unsaved draft.
                # The workspace proves the draft stayed byte-identical during
                # fetch; the server retains the exact generation projection.
                active_validation_context_fingerprint = (
                    motion_validation_context_fingerprint(
                        payload["validationContextProjection"]
                    )
                )
            else:
                raise FacilityConflictError(
                    "facility_motion_package_stale",
                    "The active revision does not match the package or repository.",
                    details={
                        "packageLayoutRevision": expected_revision,
                        "activeLayoutRevision": active_revision,
                        "repositoryRevision": current["revision"],
                    },
                )
            validate_facility_motion_package_for_playback(
                package,
                active_layout_revision=active_revision,
                active_validation_context_fingerprint=(
                    active_validation_context_fingerprint
                ),
            )
        elif active_revision != expected_revision:
            raise FacilityConflictError(
                "facility_motion_package_stale",
                "The layout changed after this motion package was generated.",
                details={
                    "packageLayoutRevision": expected_revision,
                    "activeLayoutRevision": active_revision,
                },
            )
        profile = deepcopy(payload["vehicleProfile"])
        result = {
            "package": deepcopy(payload["package"]),
            "facilityMotionEnvelope": deepcopy(
                payload["facilityMotionEnvelope"]
            ),
            "vehicleProfile": profile,
        }
        if active_validation_context_fingerprint is not None:
            result["activeValidationContextFingerprint"] = (
                active_validation_context_fingerprint
            )
        if (
            profile.get("prototypeMode") is True
            and profile.get("productionEligible") is False
        ):
            result["prototypeMode"] = True
            result["prototypeLabel"] = str(
                profile.get("prototypeLabel")
                or "Prototype vehicle profile - not production eligible"
            )
        return result

    @staticmethod
    def _activity_point_in_polygon(
        point: tuple[float, float],
        polygon: list[Mapping[str, Any]],
    ) -> bool:
        x, z = point
        inside = False
        if len(polygon) < 3:
            return False
        previous = polygon[-1]
        for current in polygon:
            x1 = float(previous.get("x", 0.0))
            z1 = float(previous.get("z", 0.0))
            x2 = float(current.get("x", 0.0))
            z2 = float(current.get("z", 0.0))
            if (
                min(x1, x2) - 1.0e-9 <= x <= max(x1, x2) + 1.0e-9
                and min(z1, z2) - 1.0e-9 <= z <= max(z1, z2) + 1.0e-9
                and abs((x2 - x1) * (z - z1) - (z2 - z1) * (x - x1))
                <= 1.0e-8
            ):
                return True
            crosses = (z1 > z) != (z2 > z)
            if crosses:
                intersection = x1 + (z - z1) * (x2 - x1) / (z2 - z1)
                if intersection >= x:
                    inside = not inside
            previous = current
        return inside

    @staticmethod
    def _activity_segments_intersect(
        left_a: tuple[float, float],
        left_b: tuple[float, float],
        right_a: tuple[float, float],
        right_b: tuple[float, float],
    ) -> bool:
        def orientation(
            a: tuple[float, float],
            b: tuple[float, float],
            c: tuple[float, float],
        ) -> float:
            return (b[0] - a[0]) * (c[1] - a[1]) - (
                b[1] - a[1]
            ) * (c[0] - a[0])

        values = (
            orientation(left_a, left_b, right_a),
            orientation(left_a, left_b, right_b),
            orientation(right_a, right_b, left_a),
            orientation(right_a, right_b, left_b),
        )
        return (
            min(values[0], values[1]) <= 1.0e-9
            and max(values[0], values[1]) >= -1.0e-9
            and min(values[2], values[3]) <= 1.0e-9
            and max(values[2], values[3]) >= -1.0e-9
            and max(min(left_a[0], left_b[0]), min(right_a[0], right_b[0]))
            <= min(max(left_a[0], left_b[0]), max(right_a[0], right_b[0]))
            + 1.0e-9
            and max(min(left_a[1], left_b[1]), min(right_a[1], right_b[1]))
            <= min(max(left_a[1], left_b[1]), max(right_a[1], right_b[1]))
            + 1.0e-9
        )

    @classmethod
    def _activity_route_department_ids(
        cls,
        layout: Mapping[str, Any],
        route: Mapping[str, Any],
    ) -> list[str]:
        centerline = [
            (float(item["x"]), float(item["z"]))
            for item in route.get("centerline", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("x"), (int, float))
            and isinstance(item.get("z"), (int, float))
        ]
        if len(centerline) < 2:
            return []
        result = []
        for zone in layout.get("zones", []):
            if not isinstance(zone, Mapping):
                continue
            extensions = zone.get("extensions")
            if isinstance(extensions, Mapping) and isinstance(
                extensions.get("cellGroup"), Mapping
            ):
                continue
            if zone.get("zoneType") in {"aisle", "exclusion"}:
                continue
            boundary = [
                item
                for item in zone.get("boundary", [])
                if isinstance(item, Mapping)
            ]
            if len(boundary) < 3:
                continue
            intersects = any(
                cls._activity_point_in_polygon(point, boundary)
                for point in centerline
            )
            if not intersects:
                polygon_points = [
                    (float(item["x"]), float(item["z"]))
                    for item in boundary
                ]
                polygon_edges = list(
                    zip(polygon_points, polygon_points[1:] + polygon_points[:1])
                )
                intersects = any(
                    cls._activity_segments_intersect(
                        route_left,
                        route_right,
                        edge_left,
                        edge_right,
                    )
                    for route_left, route_right in zip(
                        centerline,
                        centerline[1:],
                    )
                    for edge_left, edge_right in polygon_edges
                )
            if intersects and isinstance(zone.get("zoneId"), str):
                result.append(str(zone["zoneId"]))
        return sorted(set(result))

    @staticmethod
    def _prototype_actor_type(
        placement: Mapping[str, Any],
        asset_definition: Mapping[str, Any],
    ) -> str | None:
        asset_id = str(placement.get("assetId") or "").casefold()
        category = str(asset_definition.get("category") or "").casefold()
        if asset_id == "asset-operator" or category in {
            "people",
            "personnel",
            "operators",
        }:
            return "operator"
        if "forklift" in asset_id or "fork-lift" in asset_id or (
            "vehicle" in category and "bus" not in asset_id
        ):
            return "vehicle"
        if any(
            token in asset_id
            for token in (
                "pallet-truck",
                "platform-truck",
                "mobile-cart",
                "tugger",
            )
        ):
            return "mobile_equipment"
        return None

    @staticmethod
    def _prototype_actor_profile(
        principal: FacilityPrincipal,
        site_id: str,
        placement: Mapping[str, Any],
        asset_definition: Mapping[str, Any],
        actor_type: str,
    ) -> tuple[dict[str, Any], str]:
        geometry = asset_definition.get("geometry")
        aabb = geometry.get("aabb") if isinstance(geometry, Mapping) else None
        footprint_polygons = (
            geometry.get("footprintPolygons")
            if isinstance(geometry, Mapping)
            else None
        )
        if (
            not isinstance(aabb, Mapping)
            or not isinstance(aabb.get("minimum"), Mapping)
            or not isinstance(aabb.get("maximum"), Mapping)
            or not isinstance(footprint_polygons, list)
            or not footprint_polygons
            or not isinstance(footprint_polygons[0], list)
        ):
            raise FacilityValidationError(
                "facility_activity_actor_geometry_unavailable",
                "A prototype actor requires exact catalog placement geometry.",
                details={"placementId": placement.get("placementId")},
            )
        minimum = aabb["minimum"]
        maximum = aabb["maximum"]
        length = float(maximum["x"]) - float(minimum["x"])
        width = float(maximum["z"]) - float(minimum["z"])
        height = float(maximum["y"]) - float(minimum["y"])
        if min(length, width, height) <= 0:
            raise FacilityValidationError(
                "facility_activity_actor_geometry_unavailable",
                "A prototype actor requires a positive catalog envelope.",
                details={"placementId": placement.get("placementId")},
            )
        asset_ref = {
            "assetId": str(placement["assetId"]),
            "assetDefinitionRevision": str(
                placement["assetDefinitionRevision"]
            ),
        }
        identity_digest = hashlib.sha256(
            _canonical_value_bytes({
                "assetDefinitionRef": asset_ref,
                "actorType": actor_type,
            })
        ).hexdigest()
        if actor_type == "operator":
            speed = 1.2
            turning_radius = 0.2
            wheelbase = 0.2
        elif actor_type == "mobile_equipment":
            speed = 0.8
            turning_radius = max(0.4, length * 0.4)
            wheelbase = max(0.3, length * 0.5)
        else:
            speed = 1.0
            turning_radius = max(1.0, length * 0.48)
            wheelbase = max(0.5, length * 0.5)
        display_name = str(
            asset_definition.get("displayName")
            or placement.get("assetId")
        )
        profile = {
            "schemaVersion": 1,
            "documentKind": "vehicle_profile",
            "vehicleProfileId": f"prototype-actor-{identity_digest[:24]}",
            "tenantId": principal.tenant_id,
            "siteId": site_id,
            "status": "draft",
            "displayName": f"{display_name} - Prototype Activity Envelope",
            "actorType": actor_type,
            "assetDefinitionRef": asset_ref,
            "overallDimensions": {
                "length": length,
                "width": width,
                "height": height,
            },
            "footprint": [
                {
                    "x": float(point["x"]),
                    "z": float(point["z"]),
                }
                for point in footprint_polygons[0]
            ],
            "wheelbase": wheelbase,
            "steeringLimits": {
                "minimumTurningRadiusMeters": turning_radius,
            },
            "speedLimits": {"maximumMetersPerSecond": speed},
            "loadLimits": {"maximumKilograms": 0},
            "gradeLimits": {"maximumPercent": 0},
            "reversePolicy": "allowed",
            "sourceDocuments": [],
            "evidence": [],
            "unresolvedItems": [{
                "findingId": f"prototype-activity-{identity_digest[:16]}",
                "code": "prototype-actor-behavior-unverified",
                "message": (
                    "Only the exact catalog envelope and visual identity are "
                    "derived. Speed, steering, load, grade, and reverse-policy "
                    "values are synthetic presentation inputs."
                ),
            }],
            "prototypeMode": True,
            "productionEligible": False,
            "prototypeLabel": (
                "Prototype activity envelope bound to an exact catalog asset; "
                "behavior values are synthetic and not production eligible"
            ),
            "fieldAuthority": {
                "overallDimensions": "catalog_derived",
                "footprint": "catalog_derived_bounding_envelope",
                "wheelbase": "synthetic_demo",
                "steeringLimits": "synthetic_demo",
                "speedLimits": "synthetic_demo",
                "loadLimits": "synthetic_demo",
                "gradeLimits": "synthetic_demo",
                "reversePolicy": "synthetic_demo",
            },
        }
        return profile, authority_revision(profile)

    @staticmethod
    def _route_length(route: Mapping[str, Any]) -> float:
        points = [
            item
            for item in route.get("centerline", [])
            if isinstance(item, Mapping)
        ]
        return sum(
            math.hypot(
                float(right["x"]) - float(left["x"]),
                float(right["z"]) - float(left["z"]),
            )
            for left, right in zip(points, points[1:])
        )

    def _build_prototype_activity_actor_package(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        active_revision: str,
        context: FacilitySpatialContext,
        placement: Mapping[str, Any],
        route: Mapping[str, Any],
        actor_type: str,
        travel_direction: str,
        lane_adjustment_meters: float | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        asset_key = (
            str(placement["assetId"]),
            str(placement["assetDefinitionRevision"]),
        )
        asset_definition = context.asset_definitions[asset_key]
        profile_document, profile_revision = self._prototype_actor_profile(
            principal,
            site_id,
            placement,
            asset_definition,
            actor_type,
        )
        source_lane_binding = derive_directional_lane(
            draft,
            route,
            travel_direction=travel_direction,
        )
        footprint = profile_document["footprint"]
        longitudinal_extent = max(
            abs(float(point.get("x", 0.0)))
            for point in footprint
            if isinstance(point, Mapping)
        )
        placement_id = str(placement["placementId"])
        carried_ids = {
            str(item.get("placementId"))
            for item in draft.get("placements", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("snapRelationship"), Mapping)
            and item["snapRelationship"].get("supportPlacementId")
            == placement_id
            and item.get("placementId")
        }
        if lane_adjustment_meters is None:
            lane_candidates = [source_lane_binding]
            adjusted_lane = inward_lane_binding_candidate(
                route,
                source_lane_binding,
                adjustment_meters=0.5,
            )
            if adjusted_lane is not None:
                lane_candidates.append(adjusted_lane)
        else:
            adjustment = float(lane_adjustment_meters)
            if not math.isfinite(adjustment) or adjustment < 0:
                raise FacilityValidationError(
                    "facility_activity_lane_adjustment_invalid",
                    "A lane-fit adjustment must be a finite non-negative value.",
                )
            adjusted_lane = (
                source_lane_binding
                if adjustment == 0
                else inward_lane_binding_candidate(
                    route,
                    source_lane_binding,
                    adjustment_meters=adjustment,
                )
            )
            if adjusted_lane is None:
                raise FacilityValidationError(
                    "facility_activity_lane_adjustment_unavailable",
                    "The marked lane cannot be shifted inward by the requested fit adjustment.",
                    details={"routeId": route.get("routeId")},
                )
            lane_candidates = [adjusted_lane]
        obstacles = self._route_obstacles(
            draft,
            context.asset_definitions,
            context.shell,
            excluded_placement_ids={placement_id, *carried_ids},
        )
        result: dict[str, Any] = {}
        lane_binding = source_lane_binding
        for candidate_index, candidate_lane in enumerate(lane_candidates):
            centerline = inset_lane_endpoints(
                candidate_lane["laneCenterline"],
                longitudinal_extent + 0.5,
            )
            first, second = centerline[0], centerline[1]
            penultimate, last = centerline[-2], centerline[-1]
            try:
                start_heading = normalized_cardinal_route_heading(first, second)
                goal_heading = normalized_cardinal_route_heading(
                    penultimate,
                    last,
                )
            except ValueError as exc:
                raise FacilityValidationError(
                    "facility_motion_route_heading_unsupported",
                    str(exc),
                    details={"routeId": route.get("routeId")},
                ) from exc
            result = plan_forklift_route(
                {
                    "x": float(first["x"]),
                    "y": float(first.get("y", 0.0)),
                    "z": float(first["z"]),
                    "heading": start_heading,
                },
                {
                    "x": float(last["x"]),
                    "y": float(last.get("y", 0.0)),
                    "z": float(last["z"]),
                    "heading": goal_heading,
                },
                profile_document,
                traversable_polygons=route_traversable_corridor(route),
                obstacles=obstacles,
                allow_reverse=True,
                grid_resolution_meters=0.5,
                source_revisions={
                    "layout": active_revision,
                    "shell": draft["sourceShellRef"]["shellRevision"],
                    "policy": draft["policySetRef"]["policySetRevision"],
                    "vehicle": profile_revision,
                },
            )
            lane_binding = candidate_lane
            finding_codes = {
                str(item.get("code") or "")
                for item in result.get("findings", [])
                if isinstance(item, Mapping)
            }
            can_try_inward = (
                candidate_index + 1 < len(lane_candidates)
                and result.get("accepted") is not True
                and finding_codes == {"route_width_insufficient"}
            )
            if not can_try_inward:
                break
        built = build_facility_motion_package(
            result,
            layout=draft,
            layout_revision=active_revision,
            obstacle_context_revision=routing_layout_fingerprint(draft),
            route_id=str(route["routeId"]),
            vehicle_profile_ref={
                "vehicleProfileId": profile_document["vehicleProfileId"],
                "vehicleProfileRevision": profile_revision,
            },
            vehicle_placement_id=placement_id,
            lane_binding=lane_binding,
        )
        package_id = built["package"]["packageId"]
        profile_payload = deepcopy(profile_document)
        profile_payload["vehicleProfileRevision"] = profile_revision
        self.motion_package_store.put(
            package_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": active_revision,
                "package": built["package"],
                "facilityMotionEnvelope": built["facilityMotionEnvelope"],
                "vehicleProfile": profile_payload,
            },
        )
        return built, profile_payload

    def _build_prototype_lane_transfer_package(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        active_revision: str,
        context: FacilitySpatialContext,
        placement: Mapping[str, Any],
        route: Mapping[str, Any],
        profile: Mapping[str, Any],
        start_movement: Mapping[str, Any],
        goal_movement: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Plan one exact, swept-validated transfer between marked lanes."""

        if (
            start_movement.get("outcome") != "accepted"
            or goal_movement.get("outcome") != "accepted"
            or not start_movement.get("poses")
            or not goal_movement.get("poses")
        ):
            raise FacilityValidationError(
                "facility_activity_lane_exchange_unavailable",
                "A paired-lane loop requires accepted lane trajectories.",
                details={"routeId": route.get("routeId")},
            )
        placement_id = str(placement["placementId"])
        carried_ids = {
            str(item.get("placementId"))
            for item in draft.get("placements", [])
            if isinstance(item, Mapping)
            and isinstance(item.get("snapRelationship"), Mapping)
            and item["snapRelationship"].get("supportPlacementId")
            == placement_id
            and item.get("placementId")
        }
        profile_revision = str(profile["vehicleProfileRevision"])
        result = plan_forklift_route(
            start_movement["poses"][-1],
            goal_movement["poses"][0],
            profile,
            traversable_polygons=route_traversable_corridor(route),
            obstacles=self._route_obstacles(
                draft,
                context.asset_definitions,
                context.shell,
                excluded_placement_ids={placement_id, *carried_ids},
            ),
            allow_reverse=False,
            grid_resolution_meters=0.5,
            source_revisions={
                "layout": active_revision,
                "shell": draft["sourceShellRef"]["shellRevision"],
                "policy": draft["policySetRef"]["policySetRevision"],
                "vehicle": profile_revision,
            },
        )
        if result.get("accepted") is not True:
            findings = [
                item
                for item in result.get("findings", [])
                if isinstance(item, Mapping)
            ]
            raise FacilityValidationError(
                "facility_activity_lane_exchange_unavailable",
                "The actor cannot make a validated transfer into the opposite "
                "marked lane.",
                details={
                    "routeId": route.get("routeId"),
                    "placementId": placement_id,
                    "findingCodes": sorted({
                        str(item.get("code") or "")
                        for item in findings
                        if item.get("code")
                    }),
                },
            )
        transfer_poses = [
            item
            for item in result.get("poses", [])
            if isinstance(item, Mapping)
        ]
        endpoint_distance = math.hypot(
            float(goal_movement["poses"][0]["x"])
            - float(start_movement["poses"][-1]["x"]),
            float(goal_movement["poses"][0]["z"])
            - float(start_movement["poses"][-1]["z"]),
        )
        local_distance_limit = max(
            float(route.get("corridorWidth") or 0.0) * 2.0,
            endpoint_distance * math.pi * 1.5,
        )
        if (
            result.get("reverseUsed") is True
            or any(item.get("gear") == "reverse" for item in transfer_poses)
            or float(result.get("distanceMeters") or math.inf)
                > local_distance_limit
        ):
            raise FacilityValidationError(
                "facility_activity_lane_exchange_nonlocal",
                "The route planner did not produce a local forward lane exchange.",
                details={
                    "routeId": route.get("routeId"),
                    "distanceMeters": result.get("distanceMeters"),
                    "maximumLocalDistanceMeters": round(
                        local_distance_limit,
                        6,
                    ),
                },
            )
        built = build_facility_motion_package(
            result,
            layout=draft,
            layout_revision=active_revision,
            obstacle_context_revision=routing_layout_fingerprint(draft),
            route_id=str(route["routeId"]),
            vehicle_profile_ref={
                "vehicleProfileId": profile["vehicleProfileId"],
                "vehicleProfileRevision": profile_revision,
            },
            vehicle_placement_id=placement_id,
        )
        package_id = built["package"]["packageId"]
        self.motion_package_store.put(
            package_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": active_revision,
                "package": built["package"],
                "facilityMotionEnvelope": built["facilityMotionEnvelope"],
                "vehicleProfile": deepcopy(dict(profile)),
            },
        )
        return built

    def _build_prototype_local_operator_segment(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        active_revision: str,
        context: FacilitySpatialContext,
        placement: Mapping[str, Any],
        route_id: str,
        profile: Mapping[str, Any],
        start: Mapping[str, Any],
        goal: Mapping[str, Any],
        traversable_boundary: list[Mapping[str, Any]],
        excluded_placement_ids: set[str],
    ) -> dict[str, Any]:
        """Build one swept-validated leg of a derived local operator loop."""

        start_heading = self._activity_cardinal_heading(start, goal)
        goal_heading = start_heading
        profile_revision = str(profile["vehicleProfileRevision"])
        result = plan_forklift_route(
            {
                "x": float(start["x"]),
                "y": 0.0,
                "z": float(start["z"]),
                "heading": start_heading,
            },
            {
                "x": float(goal["x"]),
                "y": 0.0,
                "z": float(goal["z"]),
                "heading": goal_heading,
            },
            profile,
            traversable_polygons=[deepcopy(traversable_boundary)],
            obstacles=self._route_obstacles(
                draft,
                context.asset_definitions,
                context.shell,
                excluded_placement_ids=excluded_placement_ids,
            ),
            allow_reverse=False,
            grid_resolution_meters=0.25,
            source_revisions={
                "layout": active_revision,
                "shell": draft["sourceShellRef"]["shellRevision"],
                "policy": draft["policySetRef"]["policySetRevision"],
                "vehicle": profile_revision,
            },
        )
        if result.get("accepted") is not True:
            raise FacilityValidationError(
                "facility_activity_local_operator_path_unavailable",
                "An exact local operator loop leg could not be routed around the "
                "current placed geometry.",
                details={
                    "placementId": placement.get("placementId"),
                    "routeId": route_id,
                    "start": {
                        "x": round(float(start["x"]), 6),
                        "z": round(float(start["z"]), 6),
                    },
                    "goal": {
                        "x": round(float(goal["x"]), 6),
                        "z": round(float(goal["z"]), 6),
                    },
                    "findingCodes": sorted({
                        str(item.get("code") or "")
                        for item in result.get("findings", [])
                        if isinstance(item, Mapping) and item.get("code")
                    }),
                },
            )
        placement_id = str(placement["placementId"])
        built = build_facility_motion_package(
            result,
            layout=draft,
            layout_revision=active_revision,
            obstacle_context_revision=routing_layout_fingerprint(draft),
            route_id=route_id,
            vehicle_profile_ref={
                "vehicleProfileId": profile["vehicleProfileId"],
                "vehicleProfileRevision": profile_revision,
            },
            vehicle_placement_id=placement_id,
        )
        package_id = built["package"]["packageId"]
        self.motion_package_store.put(
            package_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": active_revision,
                "package": built["package"],
                "facilityMotionEnvelope": built["facilityMotionEnvelope"],
                "vehicleProfile": deepcopy(dict(profile)),
            },
        )
        return built

    @staticmethod
    def _activity_cardinal_heading(
        start: Mapping[str, Any],
        goal: Mapping[str, Any],
    ) -> float:
        delta_x = float(goal["x"]) - float(start["x"])
        delta_z = float(goal["z"]) - float(start["z"])
        if math.hypot(delta_x, delta_z) <= 1.0e-9:
            raise FacilityValidationError(
                "facility_activity_pedestrian_connection_unavailable",
                "A derived operator route requires distinct endpoints.",
            )
        raw_heading = math.atan2(delta_z, delta_x)
        heading_index = int(round(raw_heading / (math.pi / 2.0))) % 4
        heading = heading_index * math.pi / 2.0
        return heading - 2.0 * math.pi if heading > math.pi else heading

    @staticmethod
    def _activity_connection_boundary(
        start: Mapping[str, Any],
        goal: Mapping[str, Any],
        traversable_boundary: list[Mapping[str, Any]],
        *,
        corridor_margin: float = 3.0,
    ) -> list[Mapping[str, Any]]:
        candidate_boundary = [
            {
                "x": min(float(start["x"]), float(goal["x"])) - corridor_margin,
                "z": min(float(start["z"]), float(goal["z"])) - corridor_margin,
            },
            {
                "x": max(float(start["x"]), float(goal["x"])) + corridor_margin,
                "z": min(float(start["z"]), float(goal["z"])) - corridor_margin,
            },
            {
                "x": max(float(start["x"]), float(goal["x"])) + corridor_margin,
                "z": max(float(start["z"]), float(goal["z"])) + corridor_margin,
            },
            {
                "x": min(float(start["x"]), float(goal["x"])) - corridor_margin,
                "z": max(float(start["z"]), float(goal["z"])) + corridor_margin,
            },
        ]
        if all(
            FacilityLayoutService._activity_point_in_polygon(
                (float(point["x"]), float(point["z"])),
                traversable_boundary,
            )
            for point in candidate_boundary
        ):
            return candidate_boundary
        return deepcopy(traversable_boundary)

    @classmethod
    def _activity_station_service_cycle(
        cls,
        plan: Mapping[str, Any],
        placements_by_id: Mapping[str, Mapping[str, Any]],
        context: FacilitySpatialContext,
        profile: Mapping[str, Any],
    ) -> list[dict[str, float]]:
        """Derive a short closed cycle along assigned station service faces."""

        anchor = {
            "x": round(float(plan["anchor"]["x"]), 6),
            "z": round(float(plan["anchor"]["z"]), 6),
        }
        footprint = [
            point
            for point in profile.get("footprint", [])
            if isinstance(point, Mapping)
            and isinstance(point.get("x"), (int, float))
            and isinstance(point.get("z"), (int, float))
        ]
        if not footprint:
            return []
        # The radial envelope keeps every cardinal approach outside the station
        # footprint even as the operator turns at a service stop.
        actor_radius = max(
            math.hypot(float(point["x"]), float(point["z"]))
            for point in footprint
        ) + 0.12
        traversable_boundary = list(plan["traversableBoundary"])
        obstacle_polygons: list[
            tuple[str, list[tuple[float, float]]]
        ] = []
        for other_id, other in placements_by_id.items():
            if str(other.get("assetId") or "").casefold() == "asset-operator":
                continue
            other_asset = context.asset_definitions.get((
                str(other.get("assetId") or ""),
                str(other.get("assetDefinitionRevision") or ""),
            ))
            if not isinstance(other_asset, Mapping):
                continue
            for record in placement_spatial_records(other, other_asset):
                obstacle_polygons.append((
                    other_id,
                    [(float(point[0]), float(point[1])) for point in record.polygon],
                ))
        selected: list[dict[str, Any]] = []
        for placement_id in plan.get("assignedPlacementIds", []):
            station = placements_by_id.get(str(placement_id))
            if not isinstance(station, Mapping):
                continue
            asset = context.asset_definitions.get((
                str(station.get("assetId") or ""),
                str(station.get("assetDefinitionRevision") or ""),
            ))
            if not isinstance(asset, Mapping):
                continue
            polygon_points = [
                point
                for record in placement_spatial_records(station, asset)
                for point in record.polygon
            ]
            if not polygon_points:
                continue
            minimum_x = min(float(point[0]) for point in polygon_points)
            maximum_x = max(float(point[0]) for point in polygon_points)
            minimum_z = min(float(point[1]) for point in polygon_points)
            maximum_z = max(float(point[1]) for point in polygon_points)
            center_x = (minimum_x + maximum_x) / 2.0
            center_z = (minimum_z + maximum_z) / 2.0
            candidates = [
                {"x": minimum_x - actor_radius, "z": center_z},
                {"x": maximum_x + actor_radius, "z": center_z},
                {"x": center_x, "z": minimum_z - actor_radius},
                {"x": center_x, "z": maximum_z + actor_radius},
            ]
            candidates = [
                {
                    "x": round(float(candidate["x"]), 6),
                    "z": round(float(candidate["z"]), 6),
                }
                for candidate in candidates
                if cls._activity_point_in_polygon(
                    (float(candidate["x"]), float(candidate["z"])),
                    traversable_boundary,
                )
            ]
            if not candidates:
                continue
            inward_candidates = [
                candidate
                for candidate in candidates
                if (
                    (candidate["x"] - center_x) * (anchor["x"] - center_x)
                    + (candidate["z"] - center_z) * (anchor["z"] - center_z)
                )
                > 1.0e-9
            ]
            if inward_candidates:
                candidates = inward_candidates

            def candidate_key(candidate: Mapping[str, float]) -> tuple[Any, ...]:
                clearance = min(
                    (
                        cls._activity_point_polygon_distance(
                            (float(candidate["x"]), float(candidate["z"])),
                            polygon,
                        )
                        for owner_id, polygon in obstacle_polygons
                        if owner_id != str(placement_id)
                    ),
                    default=math.inf,
                )
                return (
                    -round(clearance, 9),
                    math.hypot(
                        float(candidate["x"]) - anchor["x"],
                        float(candidate["z"]) - anchor["z"],
                    ),
                    float(candidate["x"]),
                    float(candidate["z"]),
                )

            service_point = min(
                candidates,
                key=candidate_key,
            )
            selected.append({
                **service_point,
                "placementId": str(placement_id),
            })
        if not selected:
            return []

        angular = sorted(
            selected,
            key=lambda point: (
                math.atan2(point["z"] - anchor["z"], point["x"] - anchor["x"]),
                point["placementId"],
            ),
        )

        def cycle_key(points: list[dict[str, Any]]) -> tuple[Any, ...]:
            sequence = [anchor, *points, anchor]
            distance = sum(
                math.hypot(
                    float(right["x"]) - float(left["x"]),
                    float(right["z"]) - float(left["z"]),
                )
                for left, right in zip(sequence, sequence[1:])
            )
            return (
                round(distance, 9),
                tuple(point["placementId"] for point in points),
            )

        cycles = []
        for ordered in (angular, list(reversed(angular))):
            for index in range(len(ordered)):
                cycles.append(ordered[index:] + ordered[:index])
        ordered_service_points = min(cycles, key=cycle_key)
        return [
            anchor,
            *[
                {"x": float(point["x"]), "z": float(point["z"])}
                for point in ordered_service_points
            ],
        ]

    @classmethod
    def _activity_point_polygon_distance(
        cls,
        point: tuple[float, float],
        polygon: Sequence[tuple[float, float]],
    ) -> float:
        if len(polygon) < 3:
            return math.inf
        mapped = [{"x": item[0], "z": item[1]} for item in polygon]
        if cls._activity_point_in_polygon(point, mapped):
            return 0.0

        def segment_distance(
            start: tuple[float, float],
            end: tuple[float, float],
        ) -> float:
            delta_x = end[0] - start[0]
            delta_z = end[1] - start[1]
            denominator = delta_x * delta_x + delta_z * delta_z
            if denominator <= 1.0e-18:
                return math.hypot(point[0] - start[0], point[1] - start[1])
            factor = max(
                0.0,
                min(
                    1.0,
                    (
                        (point[0] - start[0]) * delta_x
                        + (point[1] - start[1]) * delta_z
                    )
                    / denominator,
                ),
            )
            projection = (
                start[0] + factor * delta_x,
                start[1] + factor * delta_z,
            )
            return math.hypot(
                point[0] - projection[0],
                point[1] - projection[1],
            )

        return min(
            segment_distance(start, end)
            for start, end in zip(polygon, [*polygon[1:], polygon[0]])
        )

    @staticmethod
    def _activity_fifo_goal_candidates(
        visit_plan: Mapping[str, Any],
        zone: Mapping[str, Any] | None,
        profile: Mapping[str, Any],
    ) -> list[dict[str, float]]:
        original = {
            "x": round(float(visit_plan["position"]["x"]), 6),
            "z": round(float(visit_plan["position"]["z"]), 6),
        }
        if not isinstance(zone, Mapping):
            return [original]
        boundary = [
            point
            for point in zone.get("boundary", [])
            if isinstance(point, Mapping)
            and isinstance(point.get("x"), (int, float))
            and isinstance(point.get("z"), (int, float))
        ]
        footprint = [
            point
            for point in profile.get("footprint", [])
            if isinstance(point, Mapping)
            and isinstance(point.get("x"), (int, float))
            and isinstance(point.get("z"), (int, float))
        ]
        if len(boundary) < 3 or not footprint:
            return [original]
        minimum_x = min(float(point["x"]) for point in boundary)
        maximum_x = max(float(point["x"]) for point in boundary)
        minimum_z = min(float(point["z"]) for point in boundary)
        maximum_z = max(float(point["z"]) for point in boundary)
        actor_radius = max(
            math.hypot(float(point["x"]), float(point["z"]))
            for point in footprint
        )
        computational_margin = actor_radius + 0.12
        side = min(
            (
                (abs(original["x"] - minimum_x), "minimum_x"),
                (abs(original["x"] - maximum_x), "maximum_x"),
                (abs(original["z"] - minimum_z), "minimum_z"),
                (abs(original["z"] - maximum_z), "maximum_z"),
            ),
            key=lambda item: (item[0], item[1]),
        )[1]
        alternatives = []
        if side in {"minimum_z", "maximum_z"}:
            z = minimum_z if side == "minimum_z" else maximum_z
            alternatives = [
                {"x": minimum_x + computational_margin, "z": z},
                {"x": maximum_x - computational_margin, "z": z},
            ]
        else:
            x = minimum_x if side == "minimum_x" else maximum_x
            alternatives = [
                {"x": x, "z": minimum_z + computational_margin},
                {"x": x, "z": maximum_z - computational_margin},
            ]
        alternatives = sorted(
            (
                {
                    "x": round(float(point["x"]), 6),
                    "z": round(float(point["z"]), 6),
                }
                for point in alternatives
            ),
            key=lambda point: (
                math.hypot(
                    point["x"] - original["x"],
                    point["z"] - original["z"],
                ),
                point["x"],
                point["z"],
            ),
        )
        is_assembly_cell = (
            str(zone.get("label") or "").casefold().startswith("assembly cell ")
        )
        ordered = [*alternatives, original] if is_assembly_cell else [
            original,
            *alternatives,
        ]
        result = []
        for point in ordered:
            if point not in result:
                result.append(point)
        return result

    @staticmethod
    def _simplify_activity_centerline(
        points: Sequence[Mapping[str, Any]],
        *,
        closed: bool = False,
    ) -> list[dict[str, float]]:
        """Remove duplicate and collinear samples without changing the route."""

        deduplicated: list[dict[str, float]] = []
        for source in points:
            point = {
                "x": round(float(source["x"]), 6),
                "z": round(float(source["z"]), 6),
            }
            if not deduplicated or point != deduplicated[-1]:
                deduplicated.append(point)
        if closed and deduplicated and deduplicated[-1] == deduplicated[0]:
            deduplicated.pop()
        changed = True
        while changed and len(deduplicated) > (3 if closed else 2):
            changed = False
            result: list[dict[str, float]] = []
            count = len(deduplicated)
            for index, current in enumerate(deduplicated):
                if not closed and index in {0, count - 1}:
                    result.append(current)
                    continue
                previous = deduplicated[(index - 1) % count]
                following = deduplicated[(index + 1) % count]
                first_x = current["x"] - previous["x"]
                first_z = current["z"] - previous["z"]
                second_x = following["x"] - current["x"]
                second_z = following["z"] - current["z"]
                cross = first_x * second_z - first_z * second_x
                dot = first_x * second_x + first_z * second_z
                if abs(cross) <= 1.0e-8 and dot >= 0.0:
                    changed = True
                    continue
                result.append(current)
            deduplicated = result
        if closed and deduplicated:
            deduplicated.append(deepcopy(deduplicated[0]))
        return deduplicated

    @staticmethod
    def _closest_activity_path_points(
        first: Sequence[Mapping[str, Any]],
        second: Sequence[Mapping[str, Any]],
    ) -> tuple[dict[str, float], dict[str, float]]:
        candidates = (
            (first_point, second_point)
            for first_point in first
            for second_point in second
        )
        first_point, second_point = min(
            candidates,
            key=lambda pair: (
                math.hypot(
                    float(pair[0]["x"]) - float(pair[1]["x"]),
                    float(pair[0]["z"]) - float(pair[1]["z"]),
                ),
                float(pair[0]["x"]),
                float(pair[0]["z"]),
                float(pair[1]["x"]),
                float(pair[1]["z"]),
            ),
        )
        return (
            {"x": float(first_point["x"]), "z": float(first_point["z"])},
            {"x": float(second_point["x"]), "z": float(second_point["z"])},
        )

    def _build_prototype_operator_connection(
        self,
        *,
        draft: Mapping[str, Any],
        active_revision: str,
        context: FacilitySpatialContext,
        route_id: str,
        profile: Mapping[str, Any],
        start: Mapping[str, Any],
        goal: Mapping[str, Any],
        traversable_boundary: list[Mapping[str, Any]],
        excluded_placement_ids: set[str],
    ) -> list[dict[str, float]]:
        """Route one visual pedestrian connector through exact placed geometry."""

        delta_x = float(goal["x"]) - float(start["x"])
        delta_z = float(goal["z"]) - float(start["z"])
        if math.hypot(delta_x, delta_z) <= 1.0e-9:
            raise FacilityValidationError(
                "facility_activity_pedestrian_connection_unavailable",
                "A derived pedestrian connector requires distinct local paths.",
                details={"routeId": route_id},
            )
        heading = self._activity_cardinal_heading(start, goal)
        active_boundary = self._activity_connection_boundary(
            start,
            goal,
            traversable_boundary,
        )
        result = plan_forklift_route(
            {
                "x": float(start["x"]),
                "y": 0.0,
                "z": float(start["z"]),
                "heading": heading,
            },
            {
                "x": float(goal["x"]),
                "y": 0.0,
                "z": float(goal["z"]),
                "heading": heading,
            },
            profile,
            traversable_polygons=[deepcopy(active_boundary)],
            obstacles=self._route_obstacles(
                draft,
                context.asset_definitions,
                context.shell,
                excluded_placement_ids=excluded_placement_ids,
            ),
            allow_reverse=False,
            grid_resolution_meters=0.25,
            source_revisions={
                "layout": active_revision,
                "shell": draft["sourceShellRef"]["shellRevision"],
                "policy": draft["policySetRef"]["policySetRevision"],
                "vehicle": str(profile["vehicleProfileRevision"]),
            },
        )
        if result.get("accepted") is not True:
            raise FacilityValidationError(
                "facility_activity_pedestrian_connection_unavailable",
                "A derived pedestrian connector could not be routed through the "
                "current placed geometry.",
                details={
                    "routeId": route_id,
                    "findingCodes": sorted({
                        str(item.get("code") or "")
                        for item in result.get("findings", [])
                        if isinstance(item, Mapping) and item.get("code")
                    }),
                },
            )
        return self._simplify_activity_centerline(
            result.get("poses", []),
            closed=False,
        )

    @staticmethod
    def _activity_movement_duration(movement: Mapping[str, Any]) -> float:
        if movement.get("outcome") == "accepted":
            return float(movement["plannerDurationEstimateSeconds"])
        if movement.get("outcome") == "envelope_refused":
            return float(movement["cumulativeDistance"][-1])
        raise FacilityValidationError(
            "facility_activity_actor_unroutable",
            "No replayable route was established for this actor.",
        )

    @staticmethod
    def _reference_candidate_navigation_id(prefix: str, seed: Any) -> str:
        digest = hashlib.sha256(_canonical_value_bytes(seed)).hexdigest()[:24]
        return f"{prefix}-{digest}"

    def _reference_handling_vehicle_profile(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        placement: Mapping[str, Any],
        asset_definition: Mapping[str, Any],
    ) -> tuple[dict[str, Any], str]:
        """Align exact catalog geometry with the planner's +X heading axis."""

        profile, _ = self._prototype_actor_profile(
            principal,
            site_id,
            placement,
            asset_definition,
            "vehicle",
        )
        alignment = activity_visual_alignment({
            "assetId": str(placement["assetId"]),
            "assetDefinitionRevision": str(
                placement["assetDefinitionRevision"]
            ),
        })
        forward_axis = str(alignment["forwardAxis"])

        def planner_point(point: Mapping[str, Any]) -> dict[str, float]:
            x = float(point["x"])
            z = float(point["z"])
            if forward_axis == "+X":
                transformed = (x, z)
            elif forward_axis == "-X":
                transformed = (-x, -z)
            elif forward_axis == "+Z":
                transformed = (z, -x)
            else:
                transformed = (-z, x)
            return {"x": transformed[0], "z": transformed[1]}

        footprint = [planner_point(point) for point in profile["footprint"]]
        length = max(point["x"] for point in footprint) - min(
            point["x"] for point in footprint
        )
        width = max(point["z"] for point in footprint) - min(
            point["z"] for point in footprint
        )
        profile["footprint"] = footprint
        profile["overallDimensions"]["length"] = length
        profile["overallDimensions"]["width"] = width
        profile["wheelbase"] = max(0.5, length * 0.5)
        profile["steeringLimits"]["minimumTurningRadiusMeters"] = max(
            1.0,
            length * 0.48,
        )
        profile["fieldAuthority"]["footprint"] = (
            "catalog_derived_curated_visual_axis_alignment"
        )
        profile["fieldAuthority"]["overallDimensions"] = (
            "catalog_derived_curated_visual_axis_alignment"
        )
        return profile, authority_revision(profile)

    @staticmethod
    def _reference_handling_obstacles(
        draft: Mapping[str, Any],
        context: FacilitySpatialContext,
        cycle: Mapping[str, Any],
    ) -> list[dict[str, Any]]:
        scope_ids = set(cycle["scopePlacementIds"])
        excluded_ids = set(cycle["excludedObstaclePlacementIds"])
        obstacles: list[dict[str, Any]] = []
        for placement in draft.get("placements", []):
            if (
                not isinstance(placement, Mapping)
                or placement.get("placementId") not in scope_ids
                or placement.get("placementId") in excluded_ids
            ):
                continue
            definition = context.asset_definitions.get((
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            ))
            if definition is None:
                continue
            for record in placement_spatial_records(placement, definition):
                obstacles.append({
                    "obstacleId": record.record_id,
                    "boundary": [
                        {"x": point[0], "z": point[1]}
                        for point in record.polygon
                    ],
                })
        for record in shell_obstacle_records(context.shell):
            obstacles.append({
                "obstacleId": record.record_id,
                "boundary": [
                    {"x": point[0], "z": point[1]}
                    for point in record.polygon
                ],
            })
        obstacles.sort(key=lambda item: item["obstacleId"])
        return obstacles

    def _build_reference_finished_goods_scenario(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        active_revision: str,
        preset: str,
    ) -> dict[str, Any]:
        """Build one reviewed, non-persistent Finished Goods forklift cycle."""

        if (
            layout_id != NAV0_REFERENCE_LAYOUT_ID
            or active_revision != NAV0_REFERENCE_LAYOUT_REVISION
        ):
            raise FacilityValidationError(
                "facility_navigation_reference_finished_goods_source_mismatch",
                "The Finished Goods cycle requires the exact frozen manual-layout revision.",
                details={
                    "requiredLayoutId": NAV0_REFERENCE_LAYOUT_ID,
                    "requiredLayoutRevision": NAV0_REFERENCE_LAYOUT_REVISION,
                    "activeLayoutId": layout_id,
                    "activeLayoutRevision": active_revision,
                },
            )
        context = self._spatial_context(principal, site_id, draft)
        finished_zone = next(
            (
                zone
                for zone in draft.get("zones", [])
                if isinstance(zone, Mapping)
                and zone.get("label") == "Finished Goods"
            ),
            None,
        )
        if not isinstance(finished_zone, Mapping):
            raise FacilityValidationError(
                "facility_navigation_reference_finished_goods_geometry_unavailable",
                "The reviewed Finished Goods area is unavailable.",
            )
        finished_polygon = [
            (float(point["x"]), float(point["z"]))
            for point in finished_zone.get("boundary", [])
            if isinstance(point, Mapping)
        ]
        vehicle_candidates = []
        for placement in draft.get("placements", []):
            if (
                not isinstance(placement, Mapping)
                or placement.get("assetId") != "asset-forklift"
            ):
                continue
            position = placement.get("transform", {}).get("position", {})
            if isinstance(position, Mapping) and point_in_polygon(
                (float(position["x"]), float(position["z"])),
                finished_polygon,
            ):
                vehicle_candidates.append(placement)
        if len(vehicle_candidates) != 1:
            raise FacilityValidationError(
                "facility_navigation_reference_finished_goods_inventory_mismatch",
                "The frozen Finished Goods forklift inventory changed.",
                details={"expected": 1, "actual": len(vehicle_candidates)},
            )
        vehicle = vehicle_candidates[0]
        definition = context.asset_definitions.get((
            str(vehicle["assetId"]),
            str(vehicle["assetDefinitionRevision"]),
        ))
        if not isinstance(definition, Mapping):
            raise FacilityValidationError(
                "facility_navigation_reference_finished_goods_actor_unavailable",
                "The exact Finished Goods forklift catalog revision is unavailable.",
            )
        profile, profile_revision = (
            self._reference_handling_vehicle_profile(
                principal=principal,
                site_id=site_id,
                placement=vehicle,
                asset_definition=definition,
            )
        )
        try:
            cycle = derive_reference_finished_goods_cycle(
                draft,
                context.asset_definitions,
                preset=preset,
                planner_vehicle_length_meters=float(
                    profile["overallDimensions"]["length"]
                ),
            )
        except ValueError as exc:
            raise FacilityValidationError(
                "facility_navigation_reference_finished_goods_cycle_invalid",
                str(exc),
            ) from exc
        if cycle["vehiclePlacementId"] != vehicle["placementId"]:
            raise FacilityValidationError(
                "facility_navigation_reference_finished_goods_actor_mismatch",
                "The reviewed cycle resolved a different vehicle identity.",
            )
        obstacles = self._reference_handling_obstacles(
            draft,
            context,
            cycle,
        )
        profile_ref = {
            "vehicleProfileId": str(profile["vehicleProfileId"]),
            "vehicleProfileRevision": profile_revision,
        }
        actor_payloads: dict[str, dict[str, Any]] = {}
        package_ids: list[str] = []
        segment_evidence: list[dict[str, Any]] = []
        package_endpoints: list[tuple[dict[str, Any], dict[str, Any]]] = []
        cycle_duration = 0.0
        for segment in cycle["segments"]:
            start = segment["start"]
            goal = segment["goal"]
            result = plan_forklift_route(
                {
                    "x": float(start["x"]),
                    "y": 0.0,
                    "z": float(start["z"]),
                    "heading": float(segment["startHeading"]),
                },
                {
                    "x": float(goal["x"]),
                    "y": 0.0,
                    "z": float(goal["z"]),
                    "heading": float(segment["goalHeading"]),
                },
                profile,
                traversable_polygons=cycle["traversablePolygons"],
                obstacles=obstacles,
                allow_reverse=True,
                grid_resolution_meters=0.5,
                source_revisions={
                    "layout": active_revision,
                    "shell": str(draft["sourceShellRef"]["shellRevision"]),
                    "policy": str(draft["policySetRef"]["policySetRevision"]),
                    "vehicle": profile_revision,
                },
            )
            if result.get("accepted") is not True:
                raise FacilityValidationError(
                    "facility_navigation_reference_finished_goods_unreachable",
                    "The deterministic vehicle planner refused a reviewed Finished Goods leg.",
                    details={
                        "segmentId": segment["segmentId"],
                        "outcome": result.get("outcome"),
                        "findings": deepcopy(result.get("findings") or []),
                    },
                )
            built = build_facility_motion_package(
                result,
                layout=draft,
                layout_revision=active_revision,
                obstacle_context_revision=routing_layout_fingerprint(draft),
                route_id=str(cycle["routeId"]),
                vehicle_profile_ref=profile_ref,
                vehicle_placement_id=str(vehicle["placementId"]),
            )
            package = built["package"]
            package_id = str(package["packageId"])
            profile_payload = deepcopy(profile)
            profile_payload["vehicleProfileRevision"] = profile_revision
            payload = {
                "package": deepcopy(package),
                "facilityMotionEnvelope": deepcopy(
                    built["facilityMotionEnvelope"]
                ),
                "vehicleProfile": profile_payload,
                "prototypeMode": True,
                "productionEligible": False,
            }
            actor_payloads[package_id] = payload
            self.motion_package_store.put(package_id, payload)
            movement = package["movement"]
            poses = movement["poses"]
            package_endpoints.append((poses[0], poses[-1]))
            package_ids.append(package_id)
            cycle_duration += float(
                movement["plannerDurationEstimateSeconds"]
            )
            segment_evidence.append({
                "segmentId": str(segment["segmentId"]),
                "phase": str(segment["phase"]),
                "motionPackageId": package_id,
                "distanceMeters": float(movement["distanceMeters"]),
                "turnCount": sum(
                    abs(math.atan2(
                        math.sin(
                            float(right["heading"])
                            - float(left["heading"])
                        ),
                        math.cos(
                            float(right["heading"])
                            - float(left["heading"])
                        ),
                    )) > 1.0e-6
                    for left, right in zip(poses, poses[1:])
                ),
                "displayOffsetMeters": float(
                    segment["displayOffsetMeters"]
                ),
                "loadState": (
                    "loaded_process_intent_only"
                    if segment["phase"]
                    in {"loaded_putaway", "loaded_dispatch"}
                    else "empty_process_intent_only"
                    if segment["phase"] in {"return_empty", "empty_to_rack"}
                    else "pickup_process_intent_only"
                ),
            })
        for (_, left_end), (right_start, _) in zip(
            package_endpoints,
            package_endpoints[1:] + package_endpoints[:1],
        ):
            if math.hypot(
                float(left_end["x"]) - float(right_start["x"]),
                float(left_end["z"]) - float(right_start["z"]),
            ) > 1.0e-6:
                raise FacilityValidationError(
                    "facility_navigation_reference_finished_goods_cycle_open",
                    "Finished Goods cycle legs do not join at one exact position.",
                )

        endpoint_pause_seconds = 0.75
        cycle_duration += endpoint_pause_seconds * len(package_ids)
        actor_id = (
            "actor-finished-goods-"
            + str(vehicle["placementId"])[3:15]
        )
        actor = {
            "actorId": actor_id,
            "actorType": "vehicle",
            "label": (
                "Electric Forklift - Finished Goods Put-away"
                if cycle["cycleKind"] == "finished_goods_putaway"
                else "Electric Forklift - Finished Goods Dispatch"
            ),
            "motionPackageId": package_ids[0],
            "returnMotionPackageId": None,
            "endTransferMotionPackageId": None,
            "startTransferMotionPackageId": None,
            "cycleMotionPackageIds": package_ids,
            "placementId": str(vehicle["placementId"]),
            "assetDefinitionRef": {
                "assetId": str(vehicle["assetId"]),
                "assetDefinitionRevision": str(
                    vehicle["assetDefinitionRevision"]
                ),
            },
            "routeId": str(cycle["routeId"]),
            "departmentZoneIds": [str(cycle["zoneId"])],
            "startOffsetSeconds": 0,
            "repeat": True,
            "loopMode": "closed_path",
            "endpointTurnSeconds": endpoint_pause_seconds,
            "visualAlignment": activity_visual_alignment({
                "assetId": str(vehicle["assetId"]),
                "assetDefinitionRevision": str(
                    vehicle["assetDefinitionRevision"]
                ),
            }),
        }
        scenario_label = (
            "Finished Goods put-away cycle"
            if cycle["cycleKind"] == "finished_goods_putaway"
            else "Finished Goods dispatch cycle"
        )
        scenario = build_facility_activity_scenario(
            layout_revision=active_revision,
            label=scenario_label,
            actors=[actor],
            cycle_duration_seconds=max(1.0, cycle_duration),
            stationary_evidence={
                "placementCount": len(cycle["parkedVehiclePlacementIds"]),
                "assetTypeCount": 1,
                "reason": (
                    "The existing pallet truck remains parked; only the existing "
                    "Electric Forklift is bound to this reviewed prototype cycle."
                ),
                "evidenceStatus": "unknown",
            },
        )
        loaded_phase = (
            "loaded_putaway"
            if cycle["cycleKind"] == "finished_goods_putaway"
            else "loaded_dispatch"
        )
        empty_phase = (
            "return_empty"
            if cycle["cycleKind"] == "finished_goods_putaway"
            else "empty_to_rack"
        )
        legend = []
        if cycle["cycleKind"] == "finished_goods_putaway":
            legend.append({
                "phase": "finished_goods_pick",
                "label": "Approach staged pallet",
                "lineStyle": "solid",
            })
        legend.extend([
            {
                "phase": loaded_phase,
                "label": (
                    "Loaded put-away"
                    if loaded_phase == "loaded_putaway"
                    else "Loaded to dispatch staging"
                ),
                "lineStyle": "solid",
            },
            {
                "phase": empty_phase,
                "label": (
                    "Return empty"
                    if empty_phase == "return_empty"
                    else "Empty to rack"
                ),
                "lineStyle": "dashed",
            },
        ])
        program_evidence = {
            "actorPlacementId": str(vehicle["placementId"]),
            "cycleKind": str(cycle["cycleKind"]),
            "selectedMovementProgramId": str(cycle["routeId"]),
            "requestedStopPlacementIds": [
                str(cycle["stagedPalletPlacementId"]),
                str(cycle["targetRackPlacementId"]),
            ],
            "selectedStopPlacementIds": [
                str(cycle["stagedPalletPlacementId"]),
                str(cycle["targetRackPlacementId"]),
            ],
            "omittedStopPlacementIds": [],
            "distanceMeters": round(sum(
                float(item["distanceMeters"])
                for item in segment_evidence
            ), 6),
            "turnCount": sum(
                int(item["turnCount"]) for item in segment_evidence
            ),
            "pathSegments": segment_evidence,
            "reviewedStopActions": deepcopy(cycle["reviewedStopActions"]),
            "interactionPauseSeconds": endpoint_pause_seconds,
            "timingAuthority": "derived_display_only",
            "candidateRefusals": [],
            "evidenceStatus": "inferred",
            "reviewStatus": "pending",
        }
        candidate_presentation = {
            "schemaVersion": "facility-reference-movement-candidates-v1",
            "sourceLayoutId": layout_id,
            "sourceLayoutRevision": active_revision,
            "authority": "inferred_candidate",
            "reviewStatus": "pending",
            "productionEligible": False,
            "candidateCounts": {
                "operators": 0,
                "vehicles": 1,
                "handoffs": 0,
                "displayedActors": 1,
                "displayedHandoffs": 0,
                "unavailableActors": 0,
                "partialPrograms": 0,
                "suppressedStationaryOperators": 0,
            },
            "suppressedOperatorPlacementIds": [],
            "parkedVehiclePlacementIds": deepcopy(
                cycle["parkedVehiclePlacementIds"]
            ),
            "handoffs": [],
            "finishedGoodsPathLegend": legend,
            "programEvidence": [program_evidence],
            "geometryAuthority": str(cycle["geometryAuthority"]),
            "loadValidationStatus": str(cycle["loadValidationStatus"]),
            "targetRackBayFromNorth": int(
                cycle["targetRackBayFromNorth"]
            ),
            "qualification": (
                "Reviewed prototype sequence on one existing Electric Forklift. "
                "The planner validates its exact unloaded catalog footprint against "
                "the scoped rack and staging geometry. Orange and dashed-green "
                "paths are temporal process stages on the same physical aisle; "
                "their small display offsets never enter route geometry. Pallet "
                "attachment, loaded envelope, load capacity, operating speeds, "
                "traffic interaction, throughput, safety, and compliance are not "
                "validated. The existing pallet truck remains parked."
            ),
        }
        candidate_presentation["presentationFingerprint"] = hashlib.sha256(
            _canonical_value_bytes(candidate_presentation)
        ).hexdigest()
        scenario_id = str(scenario["scenarioId"])
        self.activity_scenario_store.put(
            scenario_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": active_revision,
                "scenario": scenario,
                "actorPayloads": actor_payloads,
                "candidatePresentation": candidate_presentation,
            },
        )
        summary = facility_activity_scenario_summary(scenario)
        summary["presentationMode"] = str(cycle["cycleKind"])
        summary["candidateCounts"] = deepcopy(
            candidate_presentation["candidateCounts"]
        )
        return {
            "scenarioId": scenario_id,
            "layoutRevision": active_revision,
            "summary": summary,
            "fullScenarioPath": (
                f"/api/facility-layouts/{site_id}/{layout_id}/"
                f"activity-scenarios/{scenario_id}"
            ),
            "mutated": False,
        }

    def _build_reference_receiving_scenario(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        active_revision: str,
        preset: str,
    ) -> dict[str, Any]:
        """Build the two reviewed, non-persistent Receiving forklift cycles."""

        if (
            layout_id != NAV0_REFERENCE_LAYOUT_ID
            or active_revision != NAV0_REFERENCE_LAYOUT_REVISION
        ):
            raise FacilityValidationError(
                "facility_navigation_reference_receiving_source_mismatch",
                "Receiving cycles require the exact frozen manual-layout revision.",
                details={
                    "requiredLayoutId": NAV0_REFERENCE_LAYOUT_ID,
                    "requiredLayoutRevision": NAV0_REFERENCE_LAYOUT_REVISION,
                    "activeLayoutId": layout_id,
                    "activeLayoutRevision": active_revision,
                },
            )
        context = self._spatial_context(principal, site_id, draft)
        receiving_zone = next(
            (
                zone
                for zone in draft.get("zones", [])
                if isinstance(zone, Mapping)
                and zone.get("label") == "Receiving + Raw Material"
            ),
            None,
        )
        if not isinstance(receiving_zone, Mapping):
            raise FacilityValidationError(
                "facility_navigation_reference_receiving_geometry_unavailable",
                "The reviewed Receiving area is unavailable.",
            )
        receiving_polygon = [
            (float(point["x"]), float(point["z"]))
            for point in receiving_zone.get("boundary", [])
            if isinstance(point, Mapping)
        ]
        vehicle_candidates = []
        for placement in draft.get("placements", []):
            if (
                not isinstance(placement, Mapping)
                or placement.get("assetId")
                    != "asset-forklift-2610x2264x986-minimum-height-green"
            ):
                continue
            position = placement.get("transform", {}).get("position", {})
            if isinstance(position, Mapping) and point_in_polygon(
                (float(position["x"]), float(position["z"])),
                receiving_polygon,
            ):
                vehicle_candidates.append(placement)
        if len(vehicle_candidates) != 4:
            raise FacilityValidationError(
                "facility_navigation_reference_receiving_inventory_mismatch",
                "The frozen Receiving forklift inventory changed.",
                details={"expected": 4, "actual": len(vehicle_candidates)},
            )
        template_vehicle = sorted(
            vehicle_candidates,
            key=lambda item: str(item["placementId"]),
        )[0]
        template_definition = context.asset_definitions.get((
            str(template_vehicle["assetId"]),
            str(template_vehicle["assetDefinitionRevision"]),
        ))
        if not isinstance(template_definition, Mapping):
            raise FacilityValidationError(
                "facility_navigation_reference_receiving_actor_unavailable",
                "The exact Receiving forklift catalog revision is unavailable.",
            )
        template_profile, _ = self._reference_handling_vehicle_profile(
            principal=principal,
            site_id=site_id,
            placement=template_vehicle,
            asset_definition=template_definition,
        )
        try:
            receiving = derive_reference_receiving_cycles(
                draft,
                context.asset_definitions,
                preset=preset,
                planner_vehicle_length_meters=float(
                    template_profile["overallDimensions"]["length"]
                ),
            )
        except ValueError as exc:
            raise FacilityValidationError(
                "facility_navigation_reference_receiving_cycle_invalid",
                str(exc),
            ) from exc
        obstacles = self._reference_handling_obstacles(
            draft,
            context,
            receiving,
        )
        placement_by_id = {
            str(item["placementId"]): item
            for item in draft.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        }
        actor_payloads: dict[str, dict[str, Any]] = {}
        actors: list[dict[str, Any]] = []
        program_evidence: list[dict[str, Any]] = []
        actor_cycle_durations: list[float] = []
        endpoint_pause_seconds = 0.75

        for cycle in receiving["cycles"]:
            vehicle = placement_by_id.get(str(cycle["vehiclePlacementId"]))
            if not isinstance(vehicle, Mapping):
                raise FacilityValidationError(
                    "facility_navigation_reference_receiving_actor_mismatch",
                    "A reviewed Receiving cycle resolved an unavailable vehicle.",
                )
            definition = context.asset_definitions.get((
                str(vehicle["assetId"]),
                str(vehicle["assetDefinitionRevision"]),
            ))
            if not isinstance(definition, Mapping):
                raise FacilityValidationError(
                    "facility_navigation_reference_receiving_actor_unavailable",
                    "The exact Receiving forklift catalog revision is unavailable.",
                )
            profile, profile_revision = (
                self._reference_handling_vehicle_profile(
                    principal=principal,
                    site_id=site_id,
                    placement=vehicle,
                    asset_definition=definition,
                )
            )
            profile_ref = {
                "vehicleProfileId": str(profile["vehicleProfileId"]),
                "vehicleProfileRevision": profile_revision,
            }
            package_ids: list[str] = []
            package_endpoints: list[tuple[dict[str, Any], dict[str, Any]]] = []
            segment_evidence: list[dict[str, Any]] = []
            cycle_duration = 0.0
            for segment in cycle["segments"]:
                start = segment["start"]
                goal = segment["goal"]
                result = plan_forklift_route(
                    {
                        "x": float(start["x"]),
                        "y": 0.0,
                        "z": float(start["z"]),
                        "heading": float(segment["startHeading"]),
                    },
                    {
                        "x": float(goal["x"]),
                        "y": 0.0,
                        "z": float(goal["z"]),
                        "heading": float(segment["goalHeading"]),
                    },
                    profile,
                    traversable_polygons=segment["traversablePolygons"],
                    obstacles=obstacles,
                    allow_reverse=True,
                    grid_resolution_meters=(
                        REFERENCE_RECEIVING_PLANNER_GRID_METERS
                    ),
                    source_revisions={
                        "layout": active_revision,
                        "shell": str(draft["sourceShellRef"]["shellRevision"]),
                        "policy": str(
                            draft["policySetRef"]["policySetRevision"]
                        ),
                        "vehicle": profile_revision,
                    },
                )
                if result.get("accepted") is not True:
                    raise FacilityValidationError(
                        "facility_navigation_reference_receiving_unreachable",
                        "The deterministic vehicle planner refused a reviewed Receiving leg.",
                        details={
                            "cycleKey": cycle["cycleKey"],
                            "segmentId": segment["segmentId"],
                            "outcome": result.get("outcome"),
                            "findings": deepcopy(result.get("findings") or []),
                        },
                    )
                built = build_facility_motion_package(
                    result,
                    layout=draft,
                    layout_revision=active_revision,
                    obstacle_context_revision=routing_layout_fingerprint(draft),
                    route_id=str(cycle["routeId"]),
                    vehicle_profile_ref=profile_ref,
                    vehicle_placement_id=str(vehicle["placementId"]),
                )
                package = built["package"]
                package_id = str(package["packageId"])
                profile_payload = deepcopy(profile)
                profile_payload["vehicleProfileRevision"] = profile_revision
                payload = {
                    "package": deepcopy(package),
                    "facilityMotionEnvelope": deepcopy(
                        built["facilityMotionEnvelope"]
                    ),
                    "vehicleProfile": profile_payload,
                    "prototypeMode": True,
                    "productionEligible": False,
                }
                actor_payloads[package_id] = payload
                self.motion_package_store.put(package_id, payload)
                movement = package["movement"]
                poses = movement["poses"]
                package_endpoints.append((poses[0], poses[-1]))
                package_ids.append(package_id)
                cycle_duration += float(
                    movement["plannerDurationEstimateSeconds"]
                )
                segment_evidence.append({
                    "segmentId": str(segment["segmentId"]),
                    "phase": str(segment["phase"]),
                    "motionPackageId": package_id,
                    "distanceMeters": float(movement["distanceMeters"]),
                    "turnCount": sum(
                        abs(math.atan2(
                            math.sin(
                                float(right["heading"])
                                - float(left["heading"])
                            ),
                            math.cos(
                                float(right["heading"])
                                - float(left["heading"])
                            ),
                        )) > 1.0e-6
                        for left, right in zip(poses, poses[1:])
                    ),
                    "displayOffsetMeters": float(
                        segment["displayOffsetMeters"]
                    ),
                    "loadState": (
                        "loaded_process_intent_only"
                        if segment["phase"] == "loaded_putaway"
                        else "empty_process_intent_only"
                        if segment["phase"] == "return_empty"
                        else "pickup_process_intent_only"
                    ),
                })
            for (_, left_end), (right_start, _) in zip(
                package_endpoints,
                package_endpoints[1:] + package_endpoints[:1],
            ):
                if math.hypot(
                    float(left_end["x"]) - float(right_start["x"]),
                    float(left_end["z"]) - float(right_start["z"]),
                ) > 1.0e-6:
                    raise FacilityValidationError(
                        "facility_navigation_reference_receiving_cycle_open",
                        "Receiving cycle legs do not join at one exact position.",
                        details={"cycleKey": cycle["cycleKey"]},
                    )

            cycle_duration += endpoint_pause_seconds * len(package_ids)
            actor_cycle_durations.append(cycle_duration)
            actor = {
                "actorId": "actor-receiving-" + str(cycle["routeId"])[7:19],
                "actorType": "vehicle",
                "label": "Compact Green Forklift - " + str(cycle["cycleLabel"]),
                "motionPackageId": package_ids[0],
                "returnMotionPackageId": None,
                "endTransferMotionPackageId": None,
                "startTransferMotionPackageId": None,
                "cycleMotionPackageIds": package_ids,
                "placementId": str(vehicle["placementId"]),
                "assetDefinitionRef": {
                    "assetId": str(vehicle["assetId"]),
                    "assetDefinitionRevision": str(
                        vehicle["assetDefinitionRevision"]
                    ),
                },
                "routeId": str(cycle["routeId"]),
                "departmentZoneIds": [str(receiving["zoneId"])],
                "startOffsetSeconds": 0,
                "repeat": True,
                "loopMode": "closed_path",
                "endpointTurnSeconds": endpoint_pause_seconds,
                "visualAlignment": activity_visual_alignment({
                    "assetId": str(vehicle["assetId"]),
                    "assetDefinitionRevision": str(
                        vehicle["assetDefinitionRevision"]
                    ),
                }),
            }
            actors.append(actor)
            program_evidence.append({
                "actorPlacementId": str(vehicle["placementId"]),
                "cycleKind": str(cycle["cycleKey"]),
                "selectedMovementProgramId": str(cycle["routeId"]),
                "requestedStopPlacementIds": [
                    str(cycle["stagedPalletPlacementId"]),
                    str(cycle["targetRackPlacementId"]),
                ],
                "selectedStopPlacementIds": [
                    str(cycle["stagedPalletPlacementId"]),
                    str(cycle["targetRackPlacementId"]),
                ],
                "omittedStopPlacementIds": [],
                "distanceMeters": round(sum(
                    float(item["distanceMeters"])
                    for item in segment_evidence
                ), 6),
                "turnCount": sum(
                    int(item["turnCount"]) for item in segment_evidence
                ),
                "pathSegments": segment_evidence,
                "reviewedStopActions": deepcopy(
                    cycle["reviewedStopActions"]
                ),
                "interactionPauseSeconds": endpoint_pause_seconds,
                "timingAuthority": "derived_display_only",
                "candidateRefusals": [],
                "evidenceStatus": "inferred",
                "reviewStatus": "pending",
            })

        scenario = build_facility_activity_scenario(
            layout_revision=active_revision,
            label="Receiving pallet-to-rack cycles",
            actors=actors,
            cycle_duration_seconds=max(1.0, *actor_cycle_durations),
            stationary_evidence={
                "placementCount": len(receiving["parkedVehiclePlacementIds"]),
                "assetTypeCount": 2,
                "reason": (
                    "Two existing Compact Green Forklifts are bound to the "
                    "reviewed Receiving cycles; the other forklifts and pallet "
                    "trucks remain parked."
                ),
                "evidenceStatus": "unknown",
            },
        )
        legend = [
            {
                "phase": "receiving_pick",
                "label": "Approach inbound pallet",
                "lineStyle": "solid",
            },
            {
                "phase": "loaded_putaway",
                "label": "Loaded to assigned rack",
                "lineStyle": "solid",
            },
            {
                "phase": "return_empty",
                "label": "Return empty",
                "lineStyle": "dashed",
            },
        ]
        candidate_presentation = {
            "schemaVersion": "facility-reference-movement-candidates-v1",
            "sourceLayoutId": layout_id,
            "sourceLayoutRevision": active_revision,
            "authority": "inferred_candidate",
            "reviewStatus": "pending",
            "productionEligible": False,
            "candidateCounts": {
                "operators": 0,
                "vehicles": 2,
                "handoffs": 0,
                "displayedActors": 2,
                "displayedHandoffs": 0,
                "unavailableActors": 0,
                "partialPrograms": 0,
                "suppressedStationaryOperators": 0,
            },
            "suppressedOperatorPlacementIds": [],
            "parkedVehiclePlacementIds": deepcopy(
                receiving["parkedVehiclePlacementIds"]
            ),
            "handoffs": [],
            "receivingPathLegend": legend,
            "programEvidence": program_evidence,
            "geometryAuthority": str(receiving["geometryAuthority"]),
            "loadValidationStatus": str(receiving["loadValidationStatus"]),
            "qualification": (
                "Reviewed prototype Receiving sequences on two existing Compact "
                "Green Forklifts. The planner validates each exact unloaded catalog "
                "footprint against the scoped staging and rack geometry. Orange and "
                "dashed-green paths are loaded and empty temporal stages on the same "
                "physical aisles; display offsets never enter route geometry. Pallet "
                "attachment, loaded envelope, load capacity, rack service height, "
                "operating speeds, traffic interaction, throughput, safety, and "
                "compliance are not validated. All other Receiving mobile units "
                "remain parked."
            ),
        }
        candidate_presentation["presentationFingerprint"] = hashlib.sha256(
            _canonical_value_bytes(candidate_presentation)
        ).hexdigest()
        scenario_id = str(scenario["scenarioId"])
        self.activity_scenario_store.put(
            scenario_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": active_revision,
                "scenario": scenario,
                "actorPayloads": actor_payloads,
                "candidatePresentation": candidate_presentation,
            },
        )
        summary = facility_activity_scenario_summary(scenario)
        summary["presentationMode"] = "receiving_putaway"
        summary["candidateCounts"] = deepcopy(
            candidate_presentation["candidateCounts"]
        )
        return {
            "scenarioId": scenario_id,
            "layoutRevision": active_revision,
            "summary": summary,
            "fullScenarioPath": (
                f"/api/facility-layouts/{site_id}/{layout_id}/"
                f"activity-scenarios/{scenario_id}"
            ),
            "mutated": False,
        }

    def _build_reference_vehicle_route_journey(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        active_revision: str,
        context: FacilitySpatialContext,
        snapshot: Mapping[str, Any],
        placement: Mapping[str, Any],
        route: Mapping[str, Any],
        program: Mapping[str, Any],
        travel_direction: str,
        lane_status: str,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Wrap exact route/lane validation as one closed candidate journey."""

        outbound, profile = self._build_prototype_activity_actor_package(
            principal=principal,
            site_id=site_id,
            layout_id=layout_id,
            draft=draft,
            active_revision=active_revision,
            context=context,
            placement=placement,
            route=route,
            actor_type="vehicle",
            travel_direction=travel_direction,
        )
        outbound_movement = outbound["package"]["movement"]
        if outbound_movement.get("outcome") != "accepted":
            raise FacilityValidationError(
                "facility_navigation_reference_candidate_physical_validation_refused",
                "The exact route planner refused this vehicle candidate.",
                details={"routeId": route.get("routeId")},
            )
        package_builds = [outbound]
        closed_cycle = lane_status != "direction_markings"
        cycle_finding = None
        if lane_status == "direction_markings":
            opposite = (
                "reverse" if travel_direction == "forward" else "forward"
            )
            try:
                returning, return_profile = (
                    self._build_prototype_activity_actor_package(
                        principal=principal,
                        site_id=site_id,
                        layout_id=layout_id,
                        draft=draft,
                        active_revision=active_revision,
                        context=context,
                        placement=placement,
                        route=route,
                        actor_type="vehicle",
                        travel_direction=opposite,
                    )
                )
                returning_movement = returning["package"]["movement"]
                if (
                    returning_movement.get("outcome") != "accepted"
                    or return_profile["vehicleProfileRevision"]
                        != profile["vehicleProfileRevision"]
                ):
                    raise FacilityValidationError(
                        "facility_navigation_reference_candidate_lane_return_refused",
                        "The opposite marked lane did not produce an accepted return.",
                        details={"routeId": route.get("routeId")},
                    )
            except FacilityValidationError as exc:
                cycle_finding = str(exc.code)
            else:
                def effective_adjustment(
                    movement: Mapping[str, Any],
                ) -> float:
                    binding = movement.get("laneBinding")
                    if not isinstance(binding, Mapping):
                        return 0.0
                    try:
                        return abs(float(
                            binding.get("executionAdjustmentMeters") or 0.0
                        ))
                    except (TypeError, ValueError):
                        return 0.0

                base_adjustments = {
                    travel_direction: effective_adjustment(
                        outbound_movement
                    ),
                    opposite: effective_adjustment(returning_movement),
                }
                package_cache = {
                    (travel_direction, 0.0): (outbound, profile),
                    (opposite, 0.0): (returning, return_profile),
                }

                def lane_package(
                    direction: str,
                    extra_adjustment: float,
                ) -> tuple[dict[str, Any], dict[str, Any]]:
                    key = (direction, extra_adjustment)
                    if key not in package_cache:
                        package_cache[key] = (
                            self._build_prototype_activity_actor_package(
                                principal=principal,
                                site_id=site_id,
                                layout_id=layout_id,
                                draft=draft,
                                active_revision=active_revision,
                                context=context,
                                placement=placement,
                                route=route,
                                actor_type="vehicle",
                                travel_direction=direction,
                                lane_adjustment_meters=(
                                    base_adjustments[direction]
                                    + extra_adjustment
                                ),
                            )
                        )
                    return package_cache[key]

                fit_attempts = (
                    (0.0, 0.0),
                    (0.5, 0.0),
                    (0.0, 0.5),
                    (1.0, 0.0),
                    (0.5, 0.5),
                    (0.0, 1.0),
                )
                last_cycle_error: FacilityValidationError | None = None
                for outbound_extra, returning_extra in fit_attempts:
                    try:
                        fitted_outbound, fitted_profile = lane_package(
                            travel_direction,
                            outbound_extra,
                        )
                        fitted_returning, fitted_return_profile = lane_package(
                            opposite,
                            returning_extra,
                        )
                        if (
                            fitted_profile["vehicleProfileRevision"]
                            != fitted_return_profile["vehicleProfileRevision"]
                        ):
                            raise FacilityValidationError(
                                "facility_navigation_reference_candidate_lane_return_refused",
                                "The paired marked lanes resolved different vehicle profiles.",
                                details={"routeId": route.get("routeId")},
                            )
                        fitted_outbound_movement = fitted_outbound[
                            "package"
                        ]["movement"]
                        fitted_returning_movement = fitted_returning[
                            "package"
                        ]["movement"]
                        end_transfer = self._build_prototype_lane_transfer_package(
                            principal=principal,
                            site_id=site_id,
                            layout_id=layout_id,
                            draft=draft,
                            active_revision=active_revision,
                            context=context,
                            placement=placement,
                            route=route,
                            profile=fitted_profile,
                            start_movement=fitted_outbound_movement,
                            goal_movement=fitted_returning_movement,
                        )
                        start_transfer = self._build_prototype_lane_transfer_package(
                            principal=principal,
                            site_id=site_id,
                            layout_id=layout_id,
                            draft=draft,
                            active_revision=active_revision,
                            context=context,
                            placement=placement,
                            route=route,
                            profile=fitted_profile,
                            start_movement=fitted_returning_movement,
                            goal_movement=fitted_outbound_movement,
                        )
                    except FacilityValidationError as exc:
                        last_cycle_error = exc
                        continue
                    package_builds = [
                        fitted_outbound,
                        end_transfer,
                        fitted_returning,
                        start_transfer,
                    ]
                    profile = fitted_profile
                    closed_cycle = True
                    cycle_finding = None
                    break
                if not closed_cycle and last_cycle_error is not None:
                    cycle_finding = str(last_cycle_error.code)

        poses: list[dict[str, Any]] = []
        for package_build in package_builds:
            for raw_pose in package_build["package"]["movement"]["poses"]:
                pose = {
                    "x": float(raw_pose["x"]),
                    "z": float(raw_pose["z"]),
                    "heading": float(raw_pose.get("heading", 0)),
                    "gear": str(raw_pose.get("gear") or "forward"),
                }
                if poses and pose == poses[-1]:
                    continue
                poses.append(pose)
        if lane_status != "direction_markings":
            poses.extend({
                "x": float(pose["x"]),
                "z": float(pose["z"]),
                "heading": float(pose["heading"]),
                "gear": "reverse",
            } for pose in reversed(poses[:-1]))
        if len(poses) < 2:
            raise FacilityValidationError(
                "facility_navigation_reference_candidate_unreachable",
                "The exact route planner returned no replayable vehicle path.",
            )
        centerline = [
            {"x": pose["x"], "z": pose["z"]}
            for pose in poses
        ]
        distance = sum(
            math.hypot(
                float(right["x"]) - float(left["x"]),
                float(right["z"]) - float(left["z"]),
            )
            for left, right in zip(centerline, centerline[1:])
        )
        turn_count = sum(
            abs(math.atan2(
                math.sin(float(right["heading"]) - float(left["heading"])),
                math.cos(float(right["heading"]) - float(left["heading"])),
            )) > 1.0e-6
            for left, right in zip(poses, poses[1:])
        )
        snapshot_value = snapshot["snapshot"]
        ordered_anchor_ids = [
            str(item["navigationAnchorId"])
            for item in program["orderedStops"]
        ]
        if closed_cycle and ordered_anchor_ids[-1] != ordered_anchor_ids[0]:
            ordered_anchor_ids.append(ordered_anchor_ids[0])
        validation_fingerprint = hashlib.sha256(_canonical_value_bytes({
            "geometryContextFingerprint": snapshot_value[
                "geometryContextFingerprint"
            ],
            "movementProgramId": program["movementProgramId"],
            "routePackageIds": [
                item["package"]["packageId"] for item in package_builds
            ],
            "laneStatus": lane_status,
            "candidateCycleVersion": "reference-candidate-route-cycle-v1",
        })).hexdigest()
        journey = seal_journey_solution({
            "movementProgramId": str(program["movementProgramId"]),
            "navigationSnapshotId": str(
                snapshot_value["navigationSnapshotId"]
            ),
            "actorPlacementId": str(placement["placementId"]),
            "generationLayoutRevision": active_revision,
            "validationContextFingerprint": validation_fingerprint,
            "outcome": "accepted",
            "orderedAnchorIds": ordered_anchor_ids,
            "networkEdgeIds": [],
            "centerline": centerline,
            "poses": poses,
            "distanceMeters": distance,
            "turnCount": int(turn_count),
            "reverseUsed": any(pose["gear"] == "reverse" for pose in poses),
            "validation": {
                "identity": "pass",
                "topology": "pass",
                "direction": (
                    "pass"
                    if lane_status == "direction_markings"
                    else "unknown"
                ),
                "physical": "pass",
                "authority": "unknown",
                "stale": "pass",
            },
            "sourceRevisions": deepcopy(snapshot_value["sourceRevisions"]),
            "plannerVersions": {
                "route_planner": ROUTING_ENGINE_VERSION,
                "lane_binding": FACILITY_MOTION_LANE_BINDING_VERSION,
                "candidate_cycle": "reference-candidate-route-cycle-v1",
            },
        })
        return journey, profile, {
            "closedCycle": closed_cycle,
            "findingCode": cycle_finding,
        }

    def _build_reference_downstream_navigation_scenario(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        base_layout_revision: str,
        maximum_actors: int,
    ) -> dict[str, Any]:
        """Route existing downstream operators against cell-scoped snapshots."""

        if (
            layout_id != NAV0_REFERENCE_LAYOUT_ID
            or base_layout_revision != NAV0_REFERENCE_LAYOUT_REVISION
        ):
            raise FacilityValidationError(
                "facility_navigation_reference_downstream_source_mismatch",
                "The downstream movement prototype requires the exact frozen "
                "manual-layout revision.",
                details={
                    "requiredLayoutId": NAV0_REFERENCE_LAYOUT_ID,
                    "requiredLayoutRevision": NAV0_REFERENCE_LAYOUT_REVISION,
                    "activeLayoutId": layout_id,
                    "activeLayoutRevision": base_layout_revision,
                },
            )

        area_labels = contained_area_zone_labels(
            draft,
            [REFERENCE_DOWNSTREAM_ROOT_ZONE_LABEL],
        )
        inventory = enumerate_area(draft, area_labels)
        operator_records = sorted(
            (
                item
                for item in inventory["actors"]
                if item["actorKind"] == "operator"
            ),
            key=lambda item: str(item["placementId"]),
        )
        if len(operator_records) != 8:
            raise FacilityValidationError(
                "facility_navigation_reference_downstream_inventory_mismatch",
                "The frozen downstream operator inventory changed.",
                details={"expected": 8, "actual": len(operator_records)},
            )

        candidate_draft = deepcopy(dict(draft))
        placements = {
            str(item.get("placementId") or ""): item
            for item in candidate_draft.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        }
        context = self._spatial_context(principal, site_id, candidate_draft)
        operator_placements = [
            placements[str(item["placementId"])] for item in operator_records
        ]
        actor_asset_refs = {
            (
                str(item.get("assetId") or ""),
                str(item.get("assetDefinitionRevision") or ""),
            )
            for item in operator_placements
        }
        if len(actor_asset_refs) != 1:
            raise FacilityValidationError(
                "facility_navigation_reference_downstream_actor_mismatch",
                "Downstream operators do not share one exact catalog revision.",
            )
        actor_asset_id, actor_asset_revision = next(iter(actor_asset_refs))
        actor_definition = context.asset_definitions.get(
            (actor_asset_id, actor_asset_revision)
        )
        geometry = (
            actor_definition.get("geometry")
            if isinstance(actor_definition, Mapping)
            else None
        )
        footprints = (
            geometry.get("footprintPolygons")
            if isinstance(geometry, Mapping)
            else None
        )
        if (
            not isinstance(footprints, list)
            or not footprints
            or not isinstance(footprints[0], list)
        ):
            raise FacilityValidationError(
                "facility_navigation_actor_geometry_unavailable",
                "The exact downstream operator footprint is unavailable.",
            )
        try:
            profile = build_prototype_actor_profile(
                asset_id=actor_asset_id,
                asset_definition_revision=actor_asset_revision,
                footprint_vertices=footprints[0],
                placements=operator_placements,
            )
            itinerary = build_prototype_itinerary(
                candidate_draft,
                inventory,
                layout_revision=base_layout_revision,
                actor_profile_id=str(profile["profileId"]),
                actor_profile_revision=str(profile["profileRevision"]),
            )
            assert_itinerary_binding(
                itinerary,
                candidate_draft,
                base_layout_revision,
            )
        except ValueError as exc:
            raise FacilityValidationError(
                "facility_navigation_reference_downstream_itinerary_invalid",
                str(exc),
            ) from exc
        if itinerary["unsupportedActors"]:
            raise FacilityValidationError(
                "facility_navigation_reference_downstream_stops_unavailable",
                "One or more downstream operators has no candidate station stop.",
                details={
                    "unsupportedActors": deepcopy(
                        itinerary["unsupportedActors"]
                    )
                },
            )

        extensions = deepcopy(dict(candidate_draft.get("extensions") or {}))
        extensions["facilityNavigation"] = deepcopy(
            itinerary["facilityNavigation"]
        )
        candidate_draft["extensions"] = extensions
        candidate_draft = canonicalize_layout(candidate_draft)
        validate_layout(candidate_draft)
        self.validate_dependencies(principal, site_id, candidate_draft)
        candidate_revision = layout_revision(candidate_draft)
        context = self._spatial_context(principal, site_id, candidate_draft)
        navigation = candidate_draft["extensions"]["facilityNavigation"]
        programs = {
            str(item["movementProgramId"]): item
            for item in navigation["movementPrograms"]
        }
        anchors = {
            str(item["navigationAnchorId"]): item
            for item in navigation["anchors"]
        }
        actor_records_by_id = {
            str(item["placementId"]): item for item in operator_records
        }
        actors: list[dict[str, Any]] = []
        actor_payloads: dict[str, dict[str, Any]] = {}
        program_evidence: list[dict[str, Any]] = []
        unavailable: list[dict[str, Any]] = []
        maximum_duration = 0.0
        selected_groups = itinerary["programCandidates"][:maximum_actors]
        for group in selected_groups:
            primary_program = programs[str(group["primaryProgramId"])]
            cycle_specs = list(group.get("cycleSegments") or [])
            snapshot_anchor_ids = [
                str(anchor_id)
                for anchor_id in (
                    group.get("snapshotAnchorIds")
                    or [
                        stop["navigationAnchorId"]
                        for stop in primary_program["orderedStops"]
                    ]
                )
            ]
            snapshot = compile_navigation_snapshot_package(
                candidate_draft,
                shell=context.shell,
                asset_definitions=context.asset_definitions,
                actor_class="pedestrian",
                actor_profile_revision=str(profile["profileRevision"]),
                navigation_radius_meters=float(
                    profile["navigationRadiusMeters"]
                ),
                shell_revision=str(
                    candidate_draft["sourceShellRef"]["shellRevision"]
                ),
                policy_revision=str(
                    candidate_draft["policySetRef"]["policySetRevision"]
                ),
                evidence_authority=context.evidence_authority,
                required_anchor_ids=snapshot_anchor_ids,
            )
            actor_placement_id = str(group["actorPlacementId"])
            refused: list[dict[str, Any]] = []
            selected_segments: list[
                tuple[str, Mapping[str, Any], Mapping[str, Any]]
            ] = []
            if cycle_specs:
                for spec in cycle_specs:
                    program_id = str(spec["movementProgramId"])
                    program = programs[program_id]
                    journey = plan_pedestrian_journey(
                        candidate_draft,
                        snapshot,
                        program_id,
                    )
                    if journey["outcome"] != "accepted":
                        refused.append({
                            "movementProgramId": program_id,
                            "phase": str(spec["phase"]),
                            "outcome": str(journey["outcome"]),
                        })
                    else:
                        selected_segments.append((
                            str(spec["phase"]),
                            program,
                            journey,
                        ))
                accepted_group = (
                    len(selected_segments) == len(cycle_specs)
                    and not refused
                )
            else:
                accepted: list[
                    tuple[Mapping[str, Any], Mapping[str, Any]]
                ] = []
                for program_id in group["candidateProgramIds"]:
                    program = programs[str(program_id)]
                    journey = plan_pedestrian_journey(
                        candidate_draft,
                        snapshot,
                        str(program_id),
                    )
                    if journey["outcome"] == "accepted":
                        accepted.append((program, journey))
                    else:
                        refused.append({
                            "movementProgramId": str(program_id),
                            "outcome": str(journey["outcome"]),
                        })
                accepted_group = bool(accepted)
                if accepted:
                    program, journey = min(
                        accepted,
                        key=lambda item: (
                            -max(0, len(item[0]["orderedStops"]) - 1),
                            round(float(item[1]["distanceMeters"]), 9),
                            int(item[1]["turnCount"]),
                            str(item[0]["movementProgramId"]),
                        ),
                    )
                    selected_segments = [("candidate_loop", program, journey)]
            if not accepted_group:
                unavailable.append({
                    "actorType": "operator",
                    "placementId": actor_placement_id,
                    "routeId": str(group["primaryProgramId"]),
                    "code": "facility_navigation_reference_downstream_unreachable",
                    "reason": (
                        "No candidate stop subset produced an accepted exact "
                        "geometry journey."
                    ),
                    "evidenceStatus": "unknown",
                })
                continue

            first_program = selected_segments[0][1]
            if cycle_specs:
                selected_stop_ids = list(group["requestedStopPlacementIds"])
            else:
                selected_stop_ids = [
                    str(
                        anchors[str(stop["navigationAnchorId"])]["ownerRef"][
                            "ownerId"
                        ]
                    )
                    for stop in first_program["orderedStops"][1:]
                ]
            omitted_stop_ids = sorted(
                set(group["requestedStopPlacementIds"])
                - set(selected_stop_ids)
            )
            profile_ref = first_program["actorProfileRef"]
            placement = placements[actor_placement_id]
            definition = context.asset_definitions[(
                str(placement["assetId"]),
                str(placement["assetDefinitionRevision"]),
            )]
            package_ids: list[str] = []
            segment_evidence: list[dict[str, Any]] = []
            actor_cycle_duration = 0.0
            for phase, segment_program, journey in selected_segments:
                built = build_navigation_journey_motion_package(
                    journey,
                    actor_class="pedestrian",
                    actor_profile_ref=profile_ref,
                )
                package = built["package"]
                package_id = str(package["packageId"])
                actor_payload = {
                    "package": deepcopy(package),
                    "facilityMotionEnvelope": deepcopy(
                        built["facilityMotionEnvelope"]
                    ),
                    "actorProfile": self._navigation_actor_display_profile(
                        placement,
                        definition,
                        profile_ref,
                    ),
                    "activeValidationContextFingerprint": journey[
                        "validationContextFingerprint"
                    ],
                    "prototypeMode": True,
                    "productionEligible": False,
                }
                actor_payloads[package_id] = actor_payload
                self.motion_package_store.put(package_id, actor_payload)
                duration = float(
                    package["movement"]["presentationDurationSeconds"]
                )
                actor_cycle_duration += duration
                package_ids.append(package_id)
                segment_evidence.append({
                    "phase": phase,
                    "movementProgramId": str(
                        segment_program["movementProgramId"]
                    ),
                    "motionPackageId": package_id,
                    "distanceMeters": float(journey["distanceMeters"]),
                    "turnCount": int(journey["turnCount"]),
                })
            interaction_pause_seconds = 1.0 if cycle_specs else 0.0
            actor_cycle_duration += (
                interaction_pause_seconds * len(package_ids)
            )
            maximum_duration = max(maximum_duration, actor_cycle_duration)
            inventory_actor = actor_records_by_id[actor_placement_id]
            actor_index = len(actors) + 1
            actors.append({
                "actorId": (
                    f"actor-downstream-{actor_index:02d}-"
                    f"{actor_placement_id[3:15]}"
                ),
                "actorType": "operator",
                "label": f"Operator - {inventory_actor['zoneLabel']}",
                "motionPackageId": package_ids[0],
                "returnMotionPackageId": None,
                "endTransferMotionPackageId": None,
                "startTransferMotionPackageId": None,
                "cycleMotionPackageIds": package_ids if cycle_specs else [],
                "placementId": actor_placement_id,
                "assetDefinitionRef": {
                    "assetId": str(placement["assetId"]),
                    "assetDefinitionRevision": str(
                        placement["assetDefinitionRevision"]
                    ),
                },
                "routeId": str(first_program["movementProgramId"]),
                "departmentZoneIds": self._navigation_actor_department_ids(
                    candidate_draft,
                    placement,
                ),
                "startOffsetSeconds": 0,
                "repeat": True,
                "loopMode": "closed_path" if cycle_specs else "journey_cycle",
                "endpointTurnSeconds": interaction_pause_seconds,
                "visualAlignment": activity_visual_alignment({
                    "assetId": str(placement["assetId"]),
                    "assetDefinitionRevision": str(
                        placement["assetDefinitionRevision"]
                    ),
                }),
            })
            program_evidence.append({
                "actorPlacementId": actor_placement_id,
                "cycleKind": str(group.get("cycleKind") or "candidate"),
                "selectedMovementProgramId": str(
                    first_program["movementProgramId"]
                ),
                "requestedStopPlacementIds": list(
                    group["requestedStopPlacementIds"]
                ),
                "selectedStopPlacementIds": selected_stop_ids,
                "omittedStopPlacementIds": omitted_stop_ids,
                "distanceMeters": round(sum(
                    float(item[2]["distanceMeters"])
                    for item in selected_segments
                ), 6),
                "turnCount": sum(
                    int(item[2]["turnCount"])
                    for item in selected_segments
                ),
                "pathSegments": segment_evidence,
                "reviewedStopActions": deepcopy(
                    group.get("reviewedStopActions") or []
                ),
                "interactionPauseSeconds": interaction_pause_seconds,
                "timingAuthority": "derived_display_only",
                "candidateRefusals": refused,
                "evidenceStatus": "inferred",
                "reviewStatus": "pending",
            })

        if len(actors) != len(selected_groups):
            raise FacilityValidationError(
                "facility_navigation_reference_downstream_incomplete",
                "Not every selected downstream operator produced an accepted journey.",
                details={"unavailable": unavailable},
            )
        presentation = build_navigation_activity_presentation(
            actors,
            actor_payloads,
            cycle_duration_seconds=max(1.0, maximum_duration),
            handoff_result_ids=[],
            maximum_static_intersections_per_actor_pair=2,
        )

        stationary_asset_ids: set[str] = set()
        stationary_count = 0
        selected_placement_ids = {
            str(actor["placementId"]) for actor in actors
        }
        for placement in candidate_draft.get("placements", []):
            if (
                not isinstance(placement, Mapping)
                or placement.get("placementId") in selected_placement_ids
            ):
                continue
            definition = context.asset_definitions.get((
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            ))
            category = str(
                definition.get("category")
                if isinstance(definition, Mapping) else ""
            ).casefold()
            if category in {"machines", "automation", "machine"}:
                stationary_count += 1
                stationary_asset_ids.add(str(placement.get("assetId") or ""))

        partial_programs = sum(
            bool(item["omittedStopPlacementIds"])
            for item in program_evidence
        )
        candidate_presentation = {
            "schemaVersion": "facility-reference-movement-candidates-v1",
            "sourceLayoutId": layout_id,
            "sourceLayoutRevision": base_layout_revision,
            "authority": "inferred_candidate",
            "reviewStatus": "pending",
            "productionEligible": False,
            "candidateCounts": {
                "operators": len(operator_records),
                "vehicles": 0,
                "handoffs": 0,
                "displayedActors": len(actors),
                "displayedHandoffs": 0,
                "unavailableActors": len(unavailable),
                "partialPrograms": partial_programs,
                "suppressedStationaryOperators": 0,
            },
            "suppressedOperatorPlacementIds": [],
            "handoffs": [],
            "focusAreaLabel": REFERENCE_DOWNSTREAM_ROOT_ZONE_LABEL,
            "packagingPathLegend": [
                {
                    "phase": "carry_in",
                    "label": "Carry in",
                    "lineStyle": "solid",
                },
                {
                    "phase": "carry_out",
                    "label": "Carry out",
                    "lineStyle": "solid",
                },
                {
                    "phase": "return_empty",
                    "label": "Return empty",
                    "lineStyle": "dashed",
                },
            ],
            "inspectionPathLegend": [
                {
                    "phase": "inspection_pick",
                    "label": "Pick to inspect",
                    "lineStyle": "solid",
                },
                {
                    "phase": "inspection_place",
                    "label": "Inspect to place",
                    "lineStyle": "solid",
                },
                {
                    "phase": "return_empty",
                    "label": "Return empty",
                    "lineStyle": "dashed",
                },
            ],
            "programEvidence": program_evidence,
            "operatorProfile": deepcopy(profile),
            "qualification": (
                "Candidate presentation only. Existing operator identities and "
                "exact catalog footprints are reused. Packaging follows the "
                "reviewed input-pallet, workbench, right-side cart, and empty-"
                "return sequence. Inspection follows the reviewed left input "
                "table, laboratory workstation, right output container, and "
                "perimeter empty-return sequence. One-second stop holds are "
                "display timing only; they do not simulate handling, inspection, "
                "result recording, or process duration. Stop roles and order "
                "remain inferred prototype assumptions. "
                "This is not process approval, scheduling, staffing, ergonomics, "
                "traffic, throughput, safety, or compliance evidence."
            ),
        }
        candidate_presentation["presentationFingerprint"] = hashlib.sha256(
            _canonical_value_bytes(candidate_presentation)
        ).hexdigest()
        scenario = build_navigation_activity_scenario(
            layout_revision=candidate_revision,
            label="Downstream operator movement candidates",
            actors=actors,
            cycle_duration_seconds=max(1.0, maximum_duration),
            navigation_presentation=presentation,
            stationary_evidence={
                "placementCount": stationary_count,
                "assetTypeCount": len(stationary_asset_ids),
                "reason": (
                    "Fixed machinery remains stationary because no selected "
                    "placement has revision-bound machine kinematic evidence."
                ),
                "evidenceStatus": "unknown",
            },
            unavailable_activity=unavailable,
        )
        scenario_id = str(scenario["scenarioId"])
        self.activity_scenario_store.put(
            scenario_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": candidate_revision,
                "scenario": scenario,
                "actorPayloads": actor_payloads,
                "candidatePresentation": candidate_presentation,
            },
        )
        summary = facility_activity_scenario_summary(scenario)
        summary["presentationMode"] = "reference_downstream_candidates"
        summary["candidateCounts"] = deepcopy(
            candidate_presentation["candidateCounts"]
        )
        return {
            "scenarioId": scenario_id,
            "layoutRevision": candidate_revision,
            "summary": summary,
            "fullScenarioPath": (
                f"/api/facility-layouts/{site_id}/{layout_id}/"
                f"activity-scenarios/{scenario_id}"
            ),
            "mutated": False,
        }

    def _build_reference_candidate_navigation_scenario(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        base_layout_revision: str,
        maximum_actors: int,
    ) -> dict[str, Any]:
        """Plan the frozen reference candidates without changing the layout."""

        if (
            layout_id != NAV0_REFERENCE_LAYOUT_ID
            or base_layout_revision != NAV0_REFERENCE_LAYOUT_REVISION
        ):
            raise FacilityValidationError(
                "facility_navigation_reference_candidate_source_mismatch",
                "The reference movement candidate map requires the exact frozen "
                "manual-layout revision.",
                details={
                    "requiredLayoutId": NAV0_REFERENCE_LAYOUT_ID,
                    "requiredLayoutRevision": NAV0_REFERENCE_LAYOUT_REVISION,
                    "activeLayoutId": layout_id,
                    "activeLayoutRevision": base_layout_revision,
                },
            )
        if not self.allow_prototype_motion:
            raise FacilityValidationError(
                "facility_activity_prototype_disabled",
                "Reference movement candidates require explicit prototype mode.",
            )

        candidate_draft = deepcopy(dict(draft))
        blueprint = derive_facility_lean_motion_blueprint(candidate_draft)
        operator_plans = sorted(
            blueprint.get("operatorPlans", []),
            key=lambda item: str(item.get("planId") or ""),
        )
        if len(operator_plans) != 12:
            raise FacilityValidationError(
                "facility_navigation_reference_candidate_inventory_mismatch",
                "The frozen reference operator-candidate inventory changed.",
                details={"expected": 12, "actual": len(operator_plans)},
            )

        plans_by_zone: dict[str, list[Mapping[str, Any]]] = {}
        for plan in operator_plans:
            plans_by_zone.setdefault(str(plan["zoneId"]), []).append(plan)
        display_operator_plans: list[dict[str, Any]] = []
        for zone_id, zone_plans in sorted(plans_by_zone.items()):
            ordered_plans = sorted(
                zone_plans,
                key=lambda item: (
                    int(item.get("segmentIndex", 0)),
                    str(item.get("planId") or ""),
                ),
            )
            source_plan_ids = [str(item["planId"]) for item in ordered_plans]
            display_plan = deepcopy(dict(ordered_plans[0]))
            display_plan["sourcePlanIds"] = source_plan_ids
            if len(ordered_plans) > 1:
                display_plan["planId"] = self._reference_candidate_navigation_id(
                    "flop-display",
                    {"zoneId": zone_id, "sourcePlanIds": source_plan_ids},
                )
                display_plan["assignedPlacementIds"] = sorted({
                    str(placement_id)
                    for item in ordered_plans
                    for placement_id in item.get("assignedPlacementIds", [])
                })
                display_plan["pathKind"] = "work_area_cycle"
                display_plan["segmentIndex"] = 0
                display_plan["segmentCount"] = 1
            display_operator_plans.append(display_plan)

        placements = {
            str(item.get("placementId") or ""): item
            for item in candidate_draft.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        }
        routes = {
            str(item.get("routeId") or ""): item
            for item in candidate_draft.get("routes", [])
            if isinstance(item, Mapping) and item.get("routeId")
        }
        context = self._spatial_context(principal, site_id, candidate_draft)
        evidence_id = "evidence:reference-navigation-candidate-v1"
        navigation = {
            "schemaVersion": 1,
            "anchors": [],
            "movementPrograms": [],
            "manualPathConstraints": [],
            "handoffPrograms": [],
        }
        anchor_ids: set[str] = set()

        def add_anchor(
            *,
            seed: Mapping[str, Any],
            anchor_kind: str,
            owner_kind: str,
            owner_id: str,
            interaction_kind: str,
            actor_class: str,
            source_kind: str,
            source_id: str,
            source_revision: str,
        ) -> str:
            anchor_id = self._reference_candidate_navigation_id("na", seed)
            if anchor_id in anchor_ids:
                return anchor_id
            anchor_ids.add(anchor_id)
            navigation["anchors"].append({
                "navigationAnchorId": anchor_id,
                "anchorKind": anchor_kind,
                "ownerRef": {
                    "ownerKind": owner_kind,
                    "ownerId": owner_id,
                },
                "interactionKind": interaction_kind,
                "positionAuthority": "derived",
                "localPosition": None,
                "derivedPositionRef": {
                    "sourceKind": source_kind,
                    "sourceId": source_id,
                    "sourceRevision": source_revision,
                },
                "approachDirections": ["any"],
                "actorClasses": [actor_class],
                "evidenceStatus": "derived",
                "evidence": [evidence_id],
                "reviewStatus": "pending",
            })
            return anchor_id

        def add_program(
            *,
            seed: Mapping[str, Any],
            actor_placement_id: str,
            actor_class: str,
            profile_ref: Mapping[str, Any],
            ordered_anchor_ids: list[str],
            loop_mode: str,
            required_route_ids: list[str],
        ) -> str:
            program_id = self._reference_candidate_navigation_id("nmp", seed)
            navigation["movementPrograms"].append({
                "movementProgramId": program_id,
                "actorPlacementId": actor_placement_id,
                "actorClass": actor_class,
                "actorProfileRef": deepcopy(dict(profile_ref)),
                "orderedStops": [
                    {
                        "stopId": self._reference_candidate_navigation_id(
                            "nst",
                            {
                                "movementProgramId": program_id,
                                "navigationAnchorId": anchor_id,
                                "sequence": index,
                            },
                        ),
                        "navigationAnchorId": anchor_id,
                        "interactionKind": (
                            "none" if index == 0 else "operate"
                        ),
                        "required": True,
                    }
                    for index, anchor_id in enumerate(ordered_anchor_ids)
                ],
                "loopMode": loop_mode,
                "requiredRouteIds": list(required_route_ids),
                "requiredAnchorIds": list(ordered_anchor_ids),
                "forbiddenZoneIds": [],
                "forbiddenRouteIds": [],
                "manualPathConstraintIds": [],
                "handoffProgramIds": [],
                "sourceRevisions": {
                    "layout": base_layout_revision,
                    "actor_profile": str(profile_ref["profileRevision"]),
                },
                "evidenceStatus": "inferred",
                "evidence": [evidence_id],
                "reviewStatus": "pending",
            })
            return program_id

        program_records: list[dict[str, Any]] = []
        selected_operator_plans = display_operator_plans[:maximum_actors]
        for plan in selected_operator_plans:
            actor_id = str(plan.get("placementId") or "")
            actor = placements.get(actor_id)
            if not isinstance(actor, Mapping):
                raise FacilityValidationError(
                    "facility_navigation_reference_candidate_identity_missing",
                    "A reference operator candidate no longer resolves.",
                    details={"placementId": actor_id},
                )
            actor_revision = str(actor.get("assetDefinitionRevision") or "")
            profile_ref = {
                "profileKind": "pedestrian",
                "profileId": f"pedestrian-profile:{actor['assetId']}",
                "profileRevision": actor_revision,
            }
            home_anchor = add_anchor(
                seed={"planId": plan["planId"], "kind": "home"},
                anchor_kind="actor_home",
                owner_kind="placement",
                owner_id=actor_id,
                interaction_kind="none",
                actor_class="pedestrian",
                source_kind="placement_transform",
                source_id=actor_id,
                source_revision=actor_revision,
            )
            target_anchors = []
            target_ids = sorted(str(item) for item in plan.get(
                "assignedPlacementIds", []
            ))
            if not target_ids:
                raise FacilityValidationError(
                    "facility_navigation_reference_candidate_stops_missing",
                    "A reference operator candidate has no station identities.",
                    details={"candidateId": plan.get("planId")},
                )
            for target_id in target_ids:
                target = placements.get(target_id)
                if not isinstance(target, Mapping):
                    raise FacilityValidationError(
                        "facility_navigation_reference_candidate_identity_missing",
                        "A reference station candidate no longer resolves.",
                        details={"placementId": target_id},
                    )
                target_anchors.append(add_anchor(
                    seed={
                        "planId": plan["planId"],
                        "kind": "station",
                        "placementId": target_id,
                    },
                    anchor_kind="station_operate",
                    owner_kind="placement",
                    owner_id=target_id,
                    interaction_kind="operate",
                    actor_class="pedestrian",
                    source_kind="placement_access",
                    source_id=target_id,
                    source_revision=str(target["assetDefinitionRevision"]),
                ))
            program_id = add_program(
                seed={"candidateId": plan["planId"]},
                actor_placement_id=actor_id,
                actor_class="pedestrian",
                profile_ref=profile_ref,
                ordered_anchor_ids=[home_anchor, *target_anchors],
                loop_mode="task_cycle",
                required_route_ids=[],
            )
            actor_position = actor.get("transform", {}).get("position", {})
            fallback_targets = sorted(
                zip(target_ids, target_anchors),
                key=lambda item: (
                    -math.hypot(
                        float(
                            placements[item[0]]["transform"]["position"]["x"]
                        ) - float(actor_position.get("x", 0)),
                        float(
                            placements[item[0]]["transform"]["position"]["z"]
                        ) - float(actor_position.get("z", 0)),
                    ),
                    item[0],
                ),
            )
            fallback_program_ids = [
                add_program(
                    seed={
                        "candidateId": plan["planId"],
                        "fallbackTargetPlacementId": target_id,
                    },
                    actor_placement_id=actor_id,
                    actor_class="pedestrian",
                    profile_ref=profile_ref,
                    ordered_anchor_ids=[home_anchor, target_anchor],
                    loop_mode="task_cycle",
                    required_route_ids=[],
                )
                for target_id, target_anchor in fallback_targets
            ]
            program_records.append({
                "candidateKind": "operator",
                "candidateId": str(plan["planId"]),
                "sourceCandidateIds": list(plan["sourcePlanIds"]),
                "programId": program_id,
                "programIds": [program_id, *fallback_program_ids],
                "actorPlacementId": actor_id,
                "profileRef": profile_ref,
                "profile": None,
                "zoneId": str(plan["zoneId"]),
                "zoneLabel": str(plan["zoneLabel"]),
                "assignedPlacementIds": target_ids,
                "reviewFindings": [
                    "service_side_inferred_from_exact_free_space",
                    "station_visit_order_inferred",
                    *(
                        ["split_line_candidates_consolidated_for_presentation"]
                        if len(plan["sourcePlanIds"]) > 1 else []
                    ),
                ],
            })

        remaining = maximum_actors - len(program_records)
        for source in NAV0_VEHICLE_CANDIDATES[:max(0, remaining)]:
            placement_id = str(source["placementId"])
            placement = placements.get(placement_id)
            route_id = str(source["routeId"])
            route = routes.get(route_id)
            if (
                not isinstance(placement, Mapping)
                or not isinstance(route, Mapping)
                or placement.get("assetId") != source["assetId"]
                or placement.get("assetDefinitionRevision")
                    != source["assetDefinitionRevision"]
            ):
                raise FacilityValidationError(
                    "facility_navigation_reference_vehicle_candidate_mismatch",
                    "A frozen reference vehicle candidate changed.",
                    details={"placementId": placement_id},
                )
            definition = context.asset_definitions.get((
                str(placement["assetId"]),
                str(placement["assetDefinitionRevision"]),
            ))
            if not isinstance(definition, Mapping):
                raise FacilityValidationError(
                    "facility_navigation_actor_geometry_unavailable",
                    "The exact reference vehicle geometry is unavailable.",
                    details={"placementId": placement_id},
                )
            profile_document, profile_revision = self._prototype_actor_profile(
                principal,
                site_id,
                placement,
                definition,
                "vehicle",
            )
            profile = deepcopy(profile_document)
            profile["vehicleProfileRevision"] = profile_revision
            profile_ref = {
                "profileKind": "vehicle",
                "profileId": str(profile["vehicleProfileId"]),
                "profileRevision": profile_revision,
            }
            endpoint_order = (
                ("source", "target")
                if source["travelDirection"] == "forward"
                else ("target", "source")
            )
            route_anchors = [
                add_anchor(
                    seed={
                        "placementId": placement_id,
                        "routeId": route_id,
                        "endpoint": endpoint,
                    },
                    anchor_kind=(
                        "vehicle_parking" if index == 0
                        else "vehicle_turnaround"
                    ),
                    owner_kind="route",
                    owner_id=route_id,
                    interaction_kind="park" if index == 0 else "turnaround",
                    actor_class="vehicle",
                    source_kind="route_endpoint",
                    source_id=f"{route_id}:{endpoint}",
                    source_revision=base_layout_revision,
                )
                for index, endpoint in enumerate(endpoint_order)
            ]
            program_id = add_program(
                seed={
                    "placementId": placement_id,
                    "routeId": route_id,
                    "travelDirection": source["travelDirection"],
                },
                actor_placement_id=placement_id,
                actor_class="vehicle",
                profile_ref=profile_ref,
                ordered_anchor_ids=route_anchors,
                loop_mode=(
                    "paired_lane_return"
                    if source["laneStatus"] == "direction_markings"
                    else "out_and_return"
                ),
                required_route_ids=[route_id],
            )
            program_records.append({
                "candidateKind": "vehicle",
                "candidateId": self._reference_candidate_navigation_id(
                    "nvc", source
                ),
                "programId": program_id,
                "actorPlacementId": placement_id,
                "profileRef": profile_ref,
                "profile": profile,
                "zoneId": None,
                "zoneLabel": None,
                "routeId": route_id,
                "routeLabel": str(route.get("label") or route_id),
                "laneStatus": str(source["laneStatus"]),
                "travelDirection": str(source["travelDirection"]),
                "reviewFindings": [
                    "synthetic_operating_limits_not_production_eligible",
                    *(
                        ["directional_lane_markings_unavailable"]
                        if source["laneStatus"] == "centerline_unmarked"
                        else []
                    ),
                ],
            })

        extensions = deepcopy(dict(candidate_draft.get("extensions") or {}))
        extensions["facilityNavigation"] = navigation
        candidate_draft["extensions"] = extensions
        candidate_draft = canonicalize_layout(candidate_draft)
        validate_layout(candidate_draft)
        self.validate_dependencies(principal, site_id, candidate_draft)
        candidate_revision = layout_revision(candidate_draft)
        context = self._spatial_context(principal, site_id, candidate_draft)

        records_by_group: dict[
            tuple[str, str], list[dict[str, Any]]
        ] = {}
        for record in program_records:
            key = (
                "pedestrian" if record["candidateKind"] == "operator"
                else "vehicle",
                str(record["profileRef"]["profileRevision"]),
            )
            records_by_group.setdefault(key, []).append(record)

        actors: list[dict[str, Any]] = []
        actor_payloads: dict[str, dict[str, Any]] = {}
        unavailable: list[dict[str, Any]] = []
        actor_id_by_candidate: dict[str, str] = {}
        maximum_duration = 0.0
        for (actor_class, profile_revision), records in sorted(
            records_by_group.items(), key=lambda item: item[0]
        ):
            first_record = records[0]
            actor_placement = placements[first_record["actorPlacementId"]]
            actor_definition = context.asset_definitions[(
                str(actor_placement["assetId"]),
                str(actor_placement["assetDefinitionRevision"]),
            )]
            if actor_class == "pedestrian":
                navigation_radius = self._pedestrian_navigation_radius(
                    actor_definition
                )
            else:
                navigation_radius = self._vehicle_navigation_radius(
                    first_record["profile"]
                )
            programs_by_id = {
                str(program["movementProgramId"]): program
                for program in navigation["movementPrograms"]
            }
            required_anchor_ids: list[str] = []
            for record in records:
                for program_id in record.get(
                    "programIds", [record["programId"]]
                ):
                    program = programs_by_id[str(program_id)]
                    for anchor_id in program["requiredAnchorIds"]:
                        if anchor_id not in required_anchor_ids:
                            required_anchor_ids.append(anchor_id)
            try:
                snapshot = compile_navigation_snapshot_package(
                    candidate_draft,
                    shell=context.shell,
                    asset_definitions=context.asset_definitions,
                    actor_class=actor_class,
                    actor_profile_revision=profile_revision,
                    navigation_radius_meters=navigation_radius,
                    shell_revision=str(
                        candidate_draft["sourceShellRef"]["shellRevision"]
                    ),
                    policy_revision=str(
                        candidate_draft["policySetRef"]["policySetRevision"]
                    ),
                    evidence_authority=context.evidence_authority,
                    required_anchor_ids=required_anchor_ids,
                )
            except FacilityValidationError as exc:
                unavailable.extend({
                    "actorType": (
                        "operator"
                        if record["candidateKind"] == "operator"
                        else "vehicle"
                    ),
                    "placementId": record["actorPlacementId"],
                    "routeId": record["programId"],
                    "code": str(exc.code),
                    "reason": str(exc.message),
                    "evidenceStatus": "unknown",
                } for record in records)
                continue

            for record in records:
                try:
                    journey = None
                    selected_program_id = str(record["programId"])
                    for program_id in record.get(
                        "programIds", [record["programId"]]
                    ):
                        if actor_class == "pedestrian":
                            candidate_journey = plan_pedestrian_journey(
                                candidate_draft,
                                snapshot,
                                program_id,
                            )
                        else:
                            (
                                candidate_journey,
                                _,
                                vehicle_cycle,
                            ) = self._build_reference_vehicle_route_journey(
                                principal=principal,
                                site_id=site_id,
                                layout_id=layout_id,
                                draft=candidate_draft,
                                active_revision=candidate_revision,
                                context=context,
                                snapshot=snapshot,
                                placement=placements[
                                    record["actorPlacementId"]
                                ],
                                route=routes[record["routeId"]],
                                program=programs_by_id[str(program_id)],
                                travel_direction=record["travelDirection"],
                                lane_status=record["laneStatus"],
                            )
                            record["vehicleCycle"] = vehicle_cycle
                        journey = candidate_journey
                        if candidate_journey.get("outcome") == "accepted":
                            selected_program_id = str(program_id)
                            break
                    assert journey is not None
                    if journey.get("outcome") != "accepted":
                        outcome = str(journey.get("outcome") or "unreachable")
                        raise FacilityValidationError(
                            f"facility_navigation_reference_candidate_{outcome}",
                            "The deterministic planner returned "
                            f"{outcome} for this reference movement candidate.",
                            details={
                                "outcome": outcome,
                                "candidateId": record["candidateId"],
                                "validation": deepcopy(
                                    journey.get("validation") or {}
                                ),
                            },
                        )
                    built = build_navigation_journey_motion_package(
                        journey,
                        actor_class=actor_class,
                        actor_profile_ref=record["profileRef"],
                    )
                    placement = placements[record["actorPlacementId"]]
                    definition = context.asset_definitions[(
                        str(placement["assetId"]),
                        str(placement["assetDefinitionRevision"]),
                    )]
                    actor_profile = self._navigation_actor_display_profile(
                        placement,
                        definition,
                        record["profileRef"],
                    )
                    package = built["package"]
                    package_id = str(package["packageId"])
                    payload = {
                        "package": deepcopy(package),
                        "facilityMotionEnvelope": deepcopy(
                            built["facilityMotionEnvelope"]
                        ),
                        "actorProfile": actor_profile,
                        "activeValidationContextFingerprint": journey[
                            "validationContextFingerprint"
                        ],
                        "prototypeMode": True,
                        "productionEligible": False,
                    }
                    actor_payloads[package_id] = payload
                    self.motion_package_store.put(package_id, payload)
                    duration = float(
                        package["movement"]["presentationDurationSeconds"]
                    )
                    maximum_duration = max(maximum_duration, duration)
                    actor_index = len(actors) + 1
                    actor_id = (
                        f"actor-candidate-{actor_index:02d}-"
                        f"{record['actorPlacementId'][3:15]}"
                    )
                    for candidate_id in record.get(
                        "sourceCandidateIds", [record["candidateId"]]
                    ):
                        actor_id_by_candidate[str(candidate_id)] = actor_id
                    selected_program = programs_by_id[selected_program_id]
                    record["selectedProgramId"] = selected_program_id
                    record["selectedStopCount"] = max(
                        0, len(selected_program["orderedStops"]) - 1
                    )
                    label = (
                        f"Operator - {record['zoneLabel']}"
                        if record["candidateKind"] == "operator"
                        else f"{definition.get('displayName') or placement['assetId']}"
                            f" - {record['routeLabel']}"
                    )
                    one_way_vehicle = (
                        actor_class == "vehicle"
                        and record.get("vehicleCycle", {}).get("closedCycle")
                            is not True
                    )
                    actors.append({
                        "actorId": actor_id,
                        "actorType": (
                            "operator" if actor_class == "pedestrian"
                            else "vehicle"
                        ),
                        "label": label,
                        "motionPackageId": package_id,
                        "returnMotionPackageId": None,
                        "endTransferMotionPackageId": None,
                        "startTransferMotionPackageId": None,
                        "cycleMotionPackageIds": [],
                        "placementId": str(placement["placementId"]),
                        "assetDefinitionRef": {
                            "assetId": str(placement["assetId"]),
                            "assetDefinitionRevision": str(
                                placement["assetDefinitionRevision"]
                            ),
                        },
                        "routeId": selected_program_id,
                        "departmentZoneIds": (
                            [record["zoneId"]]
                            if record["zoneId"]
                            else self._navigation_actor_department_ids(
                                candidate_draft, placement
                            )
                        ),
                        "startOffsetSeconds": 0,
                        "repeat": not one_way_vehicle,
                        "loopMode": (
                            "once" if one_way_vehicle else "journey_cycle"
                        ),
                        "endpointTurnSeconds": 0,
                        "visualAlignment": activity_visual_alignment({
                            "assetId": str(placement["assetId"]),
                            "assetDefinitionRevision": str(
                                placement["assetDefinitionRevision"]
                            ),
                        }),
                    })
                except FacilityValidationError as exc:
                    unavailable.append({
                        "actorType": (
                            "operator"
                            if record["candidateKind"] == "operator"
                            else "vehicle"
                        ),
                        "placementId": record["actorPlacementId"],
                        "routeId": record["programId"],
                        "code": str(exc.code),
                        "reason": str(exc.message),
                        "evidenceStatus": "unknown",
                    })

        if not actors:
            raise FacilityValidationError(
                "facility_navigation_reference_candidates_unroutable",
                "No reference movement candidate produced an accepted journey.",
                details={"unavailable": unavailable},
            )

        candidate_handoffs = []
        for handoff in sorted(
            blueprint.get("materialHandoffs", []),
            key=lambda item: str(item.get("handoffId") or ""),
        ):
            from_actor = actor_id_by_candidate.get(str(handoff["fromPlanId"]))
            to_actor = actor_id_by_candidate.get(str(handoff["toPlanId"]))
            if not from_actor or not to_actor:
                continue
            candidate_handoffs.append({
                "candidateId": str(handoff["handoffId"]),
                "fromActorId": from_actor,
                "toActorId": to_actor,
                "fromZoneId": str(handoff["fromZoneId"]),
                "toZoneId": str(handoff["toZoneId"]),
                "centerline": deepcopy(handoff["centerline"]),
                "evidenceStatus": "derived",
                "reviewStatus": "pending",
                "productionEligible": False,
            })

        presentation = build_navigation_activity_presentation(
            actors,
            actor_payloads,
            cycle_duration_seconds=max(1.0, maximum_duration),
            handoff_result_ids=[],
            maximum_static_intersections_per_actor_pair=2,
        )
        selected_placements = {actor["placementId"] for actor in actors}
        suppressed_operator_placement_ids = sorted(
            str(placement.get("placementId") or "")
            for placement in candidate_draft.get("placements", [])
            if (
                isinstance(placement, Mapping)
                and placement.get("assetId") == NAV0_OPERATOR_ASSET_ID
                and placement.get("placementId") not in selected_placements
            )
        )
        stationary_asset_ids: set[str] = set()
        stationary_count = 0
        for placement in candidate_draft.get("placements", []):
            if (
                not isinstance(placement, Mapping)
                or placement.get("placementId") in selected_placements
            ):
                continue
            definition = context.asset_definitions.get((
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            ))
            category = str(
                definition.get("category")
                if isinstance(definition, Mapping) else ""
            ).casefold()
            if category in {"machines", "automation", "machine"}:
                stationary_count += 1
                stationary_asset_ids.add(str(placement.get("assetId") or ""))

        scenario = build_navigation_activity_scenario(
            layout_revision=candidate_revision,
            label="Reference movement candidates",
            actors=actors,
            cycle_duration_seconds=max(1.0, maximum_duration),
            navigation_presentation=presentation,
            stationary_evidence={
                "placementCount": stationary_count,
                "assetTypeCount": len(stationary_asset_ids),
                "reason": (
                    "Fixed machinery remains stationary because no selected "
                    "placement has revision-bound machine kinematic evidence."
                ),
                "evidenceStatus": "unknown",
            },
            unavailable_activity=unavailable,
        )
        candidate_presentation = {
            "schemaVersion": "facility-reference-movement-candidates-v1",
            "sourceLayoutId": layout_id,
            "sourceLayoutRevision": base_layout_revision,
            "authority": "inferred_candidate",
            "reviewStatus": "pending",
            "productionEligible": False,
            "candidateCounts": {
                "operators": len(operator_plans),
                "vehicles": len(NAV0_VEHICLE_CANDIDATES),
                "handoffs": len(blueprint.get("materialHandoffs", [])),
                "displayedActors": len(actors),
                "displayedHandoffs": len(candidate_handoffs),
                "unavailableActors": len(unavailable),
                "partialPrograms": sum(
                    (
                        record.get("candidateKind") == "operator"
                        and isinstance(record.get("selectedStopCount"), int)
                        and record["selectedStopCount"]
                            < len(record.get("assignedPlacementIds", []))
                    )
                    or (
                        record.get("candidateKind") == "vehicle"
                        and record.get("vehicleCycle", {}).get("closedCycle")
                            is not True
                    )
                    for record in program_records
                ),
                "suppressedStationaryOperators": len(
                    suppressed_operator_placement_ids
                ),
            },
            "suppressedOperatorPlacementIds": (
                suppressed_operator_placement_ids
            ),
            "handoffs": candidate_handoffs,
            "intersectionDisplayPolicy": {
                "maximumPerActorPair": 2,
                "qualification": (
                    "Dense overview diagnostics retain at most two deterministic "
                    "intersection points per actor pair; this is display bounding, "
                    "not collision or safety analysis."
                ),
            },
            "qualification": (
                "Candidate presentation only. Stop order, service side, vehicle "
                "operating limits, handoff timing, staffing, traffic interaction, "
                "safety, throughput, and compliance are not approved claims. "
                "Split-line candidates are consolidated to one existing operator "
                "placement per logical work area for presentation. "
                "Partial programs visit only the deterministically reachable "
                "subset reported by the presentation; a one-way vehicle "
                "candidate remains at its endpoint when no validated return "
                "transfer exists. Dense overview intersection markers are "
                "bounded to two points per actor pair and are not collision "
                "or safety analysis."
            ),
        }
        candidate_presentation["presentationFingerprint"] = hashlib.sha256(
            _canonical_value_bytes(candidate_presentation)
        ).hexdigest()
        scenario_id = str(scenario["scenarioId"])
        self.activity_scenario_store.put(
            scenario_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": candidate_revision,
                "scenario": scenario,
                "actorPayloads": actor_payloads,
                "candidatePresentation": candidate_presentation,
            },
        )
        summary = facility_activity_scenario_summary(scenario)
        summary["presentationMode"] = "reference_candidates"
        summary["candidateCounts"] = deepcopy(
            candidate_presentation["candidateCounts"]
        )
        return {
            "scenarioId": scenario_id,
            "layoutRevision": candidate_revision,
            "summary": summary,
            "fullScenarioPath": (
                f"/api/facility-layouts/{site_id}/{layout_id}/"
                f"activity-scenarios/{scenario_id}"
            ),
            "mutated": False,
        }

    def _build_reference_complete_navigation_scenario(
        self,
        *,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        draft: Mapping[str, Any],
        base_layout_revision: str,
        maximum_actors: int,
    ) -> dict[str, Any]:
        """Compose every supported reference journey without duplicating actors."""

        if maximum_actors != REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT:
            raise FacilityValidationError(
                "facility_navigation_reference_complete_actor_limit",
                "Complete reference playback binds exactly 23 existing actors.",
                details={
                    "requiredActors": REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT,
                    "maximumActors": maximum_actors,
                },
            )

        cache_key = (
            principal.tenant_id,
            site_id,
            layout_id,
            base_layout_revision,
            REFERENCE_COMPLETE_ACTIVITY_COMPILER_REVISION,
            maximum_actors,
        )
        artifact_cache_key = {
            "tenantId": principal.tenant_id,
            "siteId": site_id,
            "layoutId": layout_id,
            "layoutRevision": base_layout_revision,
            "preset": REFERENCE_COMPLETE_ACTIVITY_PRESET,
            "compilerRevision": (
                REFERENCE_COMPLETE_ACTIVITY_COMPILER_REVISION
            ),
            "maximumActors": maximum_actors,
        }
        with self._reference_complete_scenario_lock:
            cached_scenario_id = self._reference_complete_scenario_ids.get(
                cache_key
            )
        if cached_scenario_id:
            try:
                cached = self.activity_scenario_store.get(cached_scenario_id)
            except FacilityNotFoundError:
                with self._reference_complete_scenario_lock:
                    self._reference_complete_scenario_ids.pop(cache_key, None)
            else:
                cached_scenario = cached["scenario"]
                summary = facility_activity_scenario_summary(cached_scenario)
                summary["presentationMode"] = "reference_complete"
                summary["candidateCounts"] = deepcopy(
                    cached["candidatePresentation"]["candidateCounts"]
                )
                return {
                    "scenarioId": cached_scenario_id,
                    "layoutRevision": base_layout_revision,
                    "summary": summary,
                    "fullScenarioPath": (
                        f"/api/facility-layouts/{site_id}/{layout_id}/"
                        f"activity-scenarios/{cached_scenario_id}"
                    ),
                    "mutated": False,
                    "cacheHit": True,
                    "cacheSource": "memory",
                }

        artifact_payload = self.activity_scenario_artifact_cache.get(
            artifact_cache_key
        )
        if artifact_payload is not None:
            cached_scenario = artifact_payload["scenario"]
            cached_scenario_id = str(cached_scenario["scenarioId"])
            self.activity_scenario_store.put(
                cached_scenario_id,
                artifact_payload,
            )
            with self._reference_complete_scenario_lock:
                self._reference_complete_scenario_ids[cache_key] = (
                    cached_scenario_id
                )
            summary = facility_activity_scenario_summary(cached_scenario)
            summary["presentationMode"] = "reference_complete"
            summary["candidateCounts"] = deepcopy(
                artifact_payload["candidatePresentation"]["candidateCounts"]
            )
            return {
                "scenarioId": cached_scenario_id,
                "layoutRevision": base_layout_revision,
                "summary": summary,
                "fullScenarioPath": (
                    f"/api/facility-layouts/{site_id}/{layout_id}/"
                    f"activity-scenarios/{cached_scenario_id}"
                ),
                "mutated": False,
                "cacheHit": True,
                "cacheSource": "artifact",
            }

        component_results = {
            "general": self._build_reference_candidate_navigation_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                base_layout_revision=base_layout_revision,
                maximum_actors=FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS,
            ),
            "downstream": self._build_reference_downstream_navigation_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                base_layout_revision=base_layout_revision,
                maximum_actors=8,
            ),
            "receiving": self._build_reference_receiving_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                active_revision=base_layout_revision,
                preset=REFERENCE_RECEIVING_PUTAWAY_PRESET,
            ),
            "finished_goods": self._build_reference_finished_goods_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                active_revision=base_layout_revision,
                preset=REFERENCE_FINISHED_GOODS_PUTAWAY_PRESET,
            ),
        }
        components = {
            key: self.activity_scenario_store.get(str(result["scenarioId"]))
            for key, result in component_results.items()
        }

        specialized_placement_ids = {
            str(actor["placementId"])
            for key in ("downstream", "receiving", "finished_goods")
            for actor in components[key]["scenario"]["actors"]
        }
        actor_sources: list[tuple[str, Mapping[str, Any]]] = []
        general_actors = components["general"]["scenario"]["actors"]
        actor_sources.extend(
            ("general", actor)
            for actor in general_actors
            if actor["actorType"] == "operator"
        )
        actor_sources.extend(
            ("downstream", actor)
            for actor in components["downstream"]["scenario"]["actors"]
        )
        actor_sources.extend(
            ("general", actor)
            for actor in general_actors
            if actor["actorType"] != "operator"
            and str(actor["placementId"]) not in specialized_placement_ids
        )
        actor_sources.extend(
            (key, actor)
            for key in ("receiving", "finished_goods")
            for actor in components[key]["scenario"]["actors"]
        )

        actors = [deepcopy(dict(actor)) for _, actor in actor_sources]
        placement_ids = [str(actor["placementId"]) for actor in actors]
        if (
            len(actors) != REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT
            or len(set(placement_ids)) != len(placement_ids)
        ):
            raise FacilityValidationError(
                "facility_navigation_reference_complete_inventory_mismatch",
                "The supported reference movement inventory no longer resolves to "
                "23 unique existing actors.",
                details={
                    "expected": REFERENCE_COMPLETE_ACTIVITY_ACTOR_COUNT,
                    "actual": len(actors),
                    "uniquePlacements": len(set(placement_ids)),
                },
            )

        actor_payloads: dict[str, dict[str, Any]] = {}
        for source_key, actor in actor_sources:
            package_ids = [
                actor["motionPackageId"],
                actor.get("returnMotionPackageId"),
                actor.get("endTransferMotionPackageId"),
                actor.get("startTransferMotionPackageId"),
                *(actor.get("cycleMotionPackageIds") or []),
            ]
            source_payloads = components[source_key]["actorPayloads"]
            for package_id in package_ids:
                if package_id is None:
                    continue
                payload = source_payloads.get(str(package_id))
                if not isinstance(payload, Mapping):
                    raise FacilityValidationError(
                        "facility_navigation_reference_complete_package_missing",
                        "A supported reference actor lost a motion package.",
                        details={
                            "placementId": actor["placementId"],
                            "motionPackageId": package_id,
                        },
                    )
                actor_payloads[str(package_id)] = deepcopy(dict(payload))

        cycle_duration = max(
            float(component["scenario"]["cycleDurationSeconds"])
            for component in components.values()
        )
        component_presentations: dict[str, dict[str, Any]] = {}
        for source_key, component in components.items():
            component_presentation = component["scenario"].get(
                "navigationPresentation"
            )
            if not isinstance(component_presentation, Mapping):
                component_presentation = build_navigation_activity_presentation(
                    component["scenario"]["actors"],
                    component["actorPayloads"],
                    cycle_duration_seconds=float(
                        component["scenario"]["cycleDurationSeconds"]
                    ),
                    sample_count=21,
                    maximum_static_intersections_per_actor_pair=1,
                )
            component_presentations[source_key] = deepcopy(
                dict(component_presentation)
            )

        actor_source_by_id = {
            str(actor["actorId"]): source_key
            for source_key, actor in actor_sources
        }
        if len(actor_source_by_id) != len(actors):
            raise FacilityValidationError(
                "facility_navigation_reference_complete_inventory_mismatch",
                "The supported reference movement inventory contains duplicate actor IDs.",
            )
        phase_offsets = []
        path_bindings = []
        for source_key, actor in actor_sources:
            actor_id = str(actor["actorId"])
            source_presentation = component_presentations[source_key]
            source_phase = next(
                (
                    item
                    for item in source_presentation["phaseOffsets"]
                    if item["actorId"] == actor_id
                ),
                None,
            )
            source_binding = next(
                (
                    item
                    for item in source_presentation["pathBindings"]
                    if item["actorId"] == actor_id
                ),
                None,
            )
            if source_phase is None or source_binding is None:
                raise FacilityValidationError(
                    "facility_navigation_reference_complete_binding_missing",
                    "A supported reference actor lost its validated path binding.",
                    details={"actorId": actor_id, "source": source_key},
                )
            phase_offsets.append(deepcopy(dict(source_phase)))
            path_bindings.append(deepcopy(dict(source_binding)))

        path_intersections_by_id: dict[str, dict[str, Any]] = {}
        handoff_result_ids: set[str] = set()
        for source_key, source_presentation in component_presentations.items():
            handoff_result_ids.update(
                str(item)
                for item in source_presentation["handoffResultIds"]
            )
            for item in source_presentation["pathIntersections"]:
                if all(
                    actor_source_by_id.get(str(actor_id)) == source_key
                    for actor_id in item["actorIds"]
                ):
                    path_intersections_by_id[str(item["conflictId"])] = (
                        deepcopy(dict(item))
                    )

        presentation_template = component_presentations["general"]
        presentation = {
            "schemaVersion": presentation_template["schemaVersion"],
            "qualification": presentation_template["qualification"],
            "sharedClock": True,
            "processTimingClaimed": False,
            "generatedCollisionAvoidanceOffsets": False,
            "phaseOffsets": sorted(
                phase_offsets,
                key=lambda item: str(item["actorId"]),
            ),
            "pathBindings": sorted(
                path_bindings,
                key=lambda item: str(item["actorId"]),
            ),
            "pathIntersections": [
                path_intersections_by_id[key]
                for key in sorted(path_intersections_by_id)
            ],
            "sampledProximity": {
                "sampleCount": 2,
                "pairMinimums": [],
                "qualification": presentation_template[
                    "sampledProximity"
                ]["qualification"],
            },
            "handoffResultIds": sorted(handoff_result_ids),
        }

        unavailable_by_key: dict[tuple[str, str, str], dict[str, Any]] = {}
        for component in components.values():
            for item in component["scenario"]["unavailableActivity"]:
                key = (
                    str(item["placementId"]),
                    str(item["routeId"]),
                    str(item["code"]),
                )
                unavailable_by_key[key] = deepcopy(dict(item))
        unavailable = [
            unavailable_by_key[key] for key in sorted(unavailable_by_key)
        ]

        presentations = {
            key: dict(component.get("candidatePresentation") or {})
            for key, component in components.items()
        }
        selected_placement_ids = set(placement_ids)
        suppressed_operator_placement_ids = sorted(
            str(placement["placementId"])
            for placement in draft.get("placements", [])
            if (
                isinstance(placement, Mapping)
                and placement.get("assetId") == NAV0_OPERATOR_ASSET_ID
                and str(placement.get("placementId") or "")
                    not in selected_placement_ids
            )
        )
        parked_vehicle_placement_ids = sorted({
            str(placement_id)
            for key in ("receiving", "finished_goods")
            for placement_id in presentations[key].get(
                "parkedVehiclePlacementIds", []
            )
            if str(placement_id) not in selected_placement_ids
        })
        handoffs = deepcopy(presentations["general"].get("handoffs", []))
        program_evidence = [
            deepcopy(dict(item))
            for key in ("downstream", "receiving", "finished_goods")
            for item in presentations[key].get("programEvidence", [])
        ]
        partial_programs = sum(
            int(presentation_item.get("candidateCounts", {}).get(
                "partialPrograms", 0
            ))
            for presentation_item in presentations.values()
        )
        candidate_presentation = {
            "schemaVersion": "facility-reference-movement-candidates-v1",
            "sourceLayoutId": layout_id,
            "sourceLayoutRevision": base_layout_revision,
            "authority": "inferred_candidate",
            "reviewStatus": "pending",
            "productionEligible": False,
            "candidateCounts": {
                "operators": sum(
                    actor["actorType"] == "operator" for actor in actors
                ),
                "vehicles": sum(
                    actor["actorType"] == "vehicle" for actor in actors
                ),
                "handoffs": len(handoffs),
                "displayedActors": len(actors),
                "displayedHandoffs": len(handoffs),
                "unavailableActors": len(unavailable),
                "partialPrograms": partial_programs,
                "suppressedStationaryOperators": len(
                    suppressed_operator_placement_ids
                ),
            },
            "suppressedOperatorPlacementIds": (
                suppressed_operator_placement_ids
            ),
            "parkedVehiclePlacementIds": parked_vehicle_placement_ids,
            "handoffs": handoffs,
            "packagingPathLegend": deepcopy(
                presentations["downstream"].get("packagingPathLegend")
            ),
            "inspectionPathLegend": deepcopy(
                presentations["downstream"].get("inspectionPathLegend")
            ),
            "finishedGoodsPathLegend": deepcopy(
                presentations["finished_goods"].get(
                    "finishedGoodsPathLegend"
                )
            ),
            "receivingPathLegend": deepcopy(
                presentations["receiving"].get("receivingPathLegend")
            ),
            "programEvidence": program_evidence,
            "intersectionDisplayPolicy": deepcopy(
                presentations["general"].get("intersectionDisplayPolicy")
            ),
            "qualification": (
                "Combined prototype presentation of every currently supported "
                "reference movement program. It reuses 23 unique existing actor "
                "placements: Assembly and Kitting candidates, reviewed Packaging "
                "and Quality Inspection operator cycles, reviewed Receiving "
                "put-away cycles, the reviewed Finished Goods put-away cycle, and "
                "the remaining route-bound vehicles. Reviewed area programs replace "
                "older generic paths for the same placement. Shared playback does "
                "not establish scheduling, traffic interaction, process timing, "
                "load behavior, throughput, safety, or compliance."
            ),
        }
        candidate_presentation["presentationFingerprint"] = hashlib.sha256(
            _canonical_value_bytes(candidate_presentation)
        ).hexdigest()

        stationary_evidence = deepcopy(
            components["general"]["scenario"]["stationaryEvidence"]
        )
        scenario = build_navigation_activity_scenario(
            layout_revision=base_layout_revision,
            label="Complete reference movement",
            actors=actors,
            cycle_duration_seconds=cycle_duration,
            navigation_presentation=presentation,
            stationary_evidence=stationary_evidence,
            unavailable_activity=unavailable,
        )
        scenario_id = str(scenario["scenarioId"])
        stored_payload = {
            "tenantId": principal.tenant_id,
            "siteId": site_id,
            "layoutId": layout_id,
            "layoutRevision": base_layout_revision,
            "scenario": scenario,
            "actorPayloads": actor_payloads,
            "candidatePresentation": candidate_presentation,
        }
        self.activity_scenario_store.put(scenario_id, stored_payload)
        cache_persisted = True
        try:
            self.activity_scenario_artifact_cache.put(
                artifact_cache_key,
                stored_payload,
            )
        except FacilityValidationError:
            cache_persisted = False
        with self._reference_complete_scenario_lock:
            self._reference_complete_scenario_ids[cache_key] = scenario_id
        summary = facility_activity_scenario_summary(scenario)
        summary["presentationMode"] = "reference_complete"
        summary["candidateCounts"] = deepcopy(
            candidate_presentation["candidateCounts"]
        )
        return {
            "scenarioId": scenario_id,
            "layoutRevision": base_layout_revision,
            "summary": summary,
            "fullScenarioPath": (
                f"/api/facility-layouts/{site_id}/{layout_id}/"
                f"activity-scenarios/{scenario_id}"
            ),
            "mutated": False,
            "cacheHit": False,
            "cachePersisted": cache_persisted,
        }

    def build_prototype_activity_scenario(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Build a read-only multi-actor prototype from exact layout identities."""

        preset = str(request.get("preset") or "")
        reference_complete_mode = (
            preset == REFERENCE_COMPLETE_ACTIVITY_PRESET
        )
        reference_candidate_mode = preset == "reference_candidate_navigation"
        reference_downstream_mode = (
            preset == REFERENCE_DOWNSTREAM_ACTIVITY_PRESET
        )
        reference_finished_goods_mode = (
            preset in REFERENCE_FINISHED_GOODS_PRESETS
        )
        reference_receiving_mode = (
            preset == REFERENCE_RECEIVING_PUTAWAY_PRESET
        )
        if (
            not reference_complete_mode
            and not reference_candidate_mode
            and not reference_downstream_mode
            and not reference_finished_goods_mode
            and not reference_receiving_mode
            and not self.allow_legacy_lean_motion_fixture
        ):
            raise FacilityValidationError(
                "facility_legacy_navigation_fixture_only",
                "The rectangle-loop activity heuristic is isolated to test fixtures. "
                "Use revision-bound navigation movement programs instead.",
            )
        pending = list(operations or [])
        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.edit" if pending else "layout.read",
        )
        if not self.allow_prototype_motion:
            raise FacilityValidationError(
                "facility_activity_prototype_disabled",
                "Prototype activity playback is disabled for this host.",
            )
        allowed_fields = {
            "preset",
            "prototypeMode",
            "scenarioLabel",
            "maximumActors",
        }
        unknown = sorted(set(request) - allowed_fields)
        if unknown:
            raise FacilityValidationError(
                "facility_activity_request_unknown_field",
                "Activity requests accept the closed semantic preset only.",
                details={"unknownFields": unknown},
            )
        if (
            preset not in {
                "mobile_actors_on_authored_routes",
                REFERENCE_COMPLETE_ACTIVITY_PRESET,
                "reference_candidate_navigation",
                REFERENCE_DOWNSTREAM_ACTIVITY_PRESET,
                *REFERENCE_FINISHED_GOODS_PRESETS,
                REFERENCE_RECEIVING_PUTAWAY_PRESET,
            }
            or request.get("prototypeMode") is not True
        ):
            raise FacilityValidationError(
                "facility_activity_request_invalid",
                "The supported activity preset requires explicit prototype mode.",
            )
        maximum_actors = request.get(
            "maximumActors",
            FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS,
        )
        if (
            isinstance(maximum_actors, bool)
            or not isinstance(maximum_actors, int)
            or maximum_actors < 1
            or maximum_actors > FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS
        ):
            raise FacilityValidationError(
                "facility_activity_request_invalid",
                "maximumActors is outside the supported range.",
                details={
                    "maximumActors": FACILITY_ACTIVITY_SCENARIO_MAXIMUM_ACTORS,
                },
            )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        if current["revision"] != base_revision:
            raise FacilityConflictError(
                "revision_conflict",
                "Facility Layout revision conflict.",
                details={"currentRevision": current["revision"]},
            )
        draft = apply_facility_layout_operations(
            current["layout"],
            pending,
            base_revision=base_revision,
        )["document"]
        self.validate_dependencies(principal, site_id, draft)
        active_revision = layout_revision(draft)
        if reference_complete_mode:
            return self._build_reference_complete_navigation_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                base_layout_revision=active_revision,
                maximum_actors=maximum_actors,
            )
        if reference_candidate_mode:
            return self._build_reference_candidate_navigation_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                base_layout_revision=active_revision,
                maximum_actors=maximum_actors,
            )
        if reference_downstream_mode:
            return self._build_reference_downstream_navigation_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                base_layout_revision=active_revision,
                maximum_actors=maximum_actors,
            )
        if reference_finished_goods_mode:
            if maximum_actors != 1:
                raise FacilityValidationError(
                    "facility_navigation_reference_finished_goods_actor_limit",
                    "The reviewed Finished Goods cycle binds exactly one existing forklift.",
                    details={"maximumActors": maximum_actors},
                )
            return self._build_reference_finished_goods_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                active_revision=active_revision,
                preset=preset,
            )
        if reference_receiving_mode:
            if maximum_actors != 2:
                raise FacilityValidationError(
                    "facility_navigation_reference_receiving_actor_limit",
                    "The reviewed Receiving presentation binds exactly two existing forklifts.",
                    details={"maximumActors": maximum_actors},
                )
            return self._build_reference_receiving_scenario(
                principal=principal,
                site_id=site_id,
                layout_id=layout_id,
                draft=draft,
                active_revision=active_revision,
                preset=preset,
            )
        context = self._spatial_context(principal, site_id, draft)
        material_routes = sorted(
            (
                route
                for route in draft.get("routes", [])
                if isinstance(route, Mapping)
                and route.get("routeKind") in {"forklift", "material"}
            ),
            key=lambda route: (
                -self._route_length(route),
                str(route.get("routeId") or ""),
            ),
        )
        operator_routes = sorted(
            (
                route
                for route in draft.get("routes", [])
                if isinstance(route, Mapping)
                and route.get("routeKind") in {"operator", "pedestrian"}
            ),
            key=lambda route: (
                -self._route_length(route),
                str(route.get("routeId") or ""),
            ),
        )
        if not material_routes and not operator_routes:
            raise FacilityValidationError(
                "facility_activity_routes_unavailable",
                "The active layout has no authored routes for activity playback.",
            )
        candidates: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {
            "vehicle": [],
            "operator": [],
            "mobile_equipment": [],
        }
        for placement in draft.get("placements", []):
            if not isinstance(placement, Mapping):
                continue
            asset_key = (
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            )
            definition = context.asset_definitions.get(asset_key)
            if not isinstance(definition, Mapping):
                continue
            actor_type = self._prototype_actor_type(placement, definition)
            if actor_type is not None:
                candidates[actor_type].append((placement, definition))
        for actor_type in candidates:
            candidates[actor_type].sort(
                key=lambda item: (
                    str(item[0].get("assetId") or ""),
                    str(item[0].get("placementId") or ""),
                )
            )
        def vehicle_length(item: tuple[Mapping[str, Any], Mapping[str, Any]]) -> float:
            geometry = item[1].get("geometry")
            aabb = geometry.get("aabb") if isinstance(geometry, Mapping) else None
            try:
                return abs(
                    float(aabb["maximum"]["x"])
                    - float(aabb["minimum"]["x"])
                )
            except (KeyError, TypeError, ValueError):
                return math.inf

        vehicle_groups: dict[tuple[str, str], list[tuple[Mapping[str, Any], Mapping[str, Any]]]] = {}
        for item in candidates["vehicle"]:
            key = (
                str(item[0].get("assetId") or ""),
                str(item[0].get("assetDefinitionRevision") or ""),
            )
            vehicle_groups.setdefault(key, []).append(item)

        def vehicle_visual_rank(
            group: list[tuple[Mapping[str, Any], Mapping[str, Any]]],
        ) -> int:
            placement = group[0][0]
            try:
                activity_visual_alignment({
                    "assetId": str(placement.get("assetId") or ""),
                    "assetDefinitionRevision": str(
                        placement.get("assetDefinitionRevision") or ""
                    ),
                })
            except FacilityValidationError:
                return 1
            return 0

        ordered_vehicle_groups = sorted(
            vehicle_groups.values(),
            key=lambda group: (
                vehicle_visual_rank(group),
                vehicle_length(group[0]),
                str(group[0][0].get("assetId") or ""),
            ),
        )
        candidates["vehicle"] = [
            group[0] for group in ordered_vehicle_groups
        ] + [
            item
            for group in ordered_vehicle_groups
            for item in group[1:]
        ]
        lean_blueprint = derive_facility_lean_motion_blueprint(draft)
        operator_placements = {
            str(placement.get("placementId") or ""): placement
            for placement, _ in candidates["operator"]
        }
        local_operator_plans = [
            plan
            for plan in lean_blueprint["operatorPlans"]
            if plan["placementId"] in operator_placements
        ][:maximum_actors]
        operator_slots = 0 if local_operator_plans else min(
            3,
            len(operator_routes),
            len(candidates["operator"]),
            maximum_actors,
        )
        material_slots = min(
            maximum_actors - operator_slots - len(local_operator_plans),
            len(candidates["vehicle"]) + len(candidates["mobile_equipment"]),
            max(0, len(material_routes) + (1 if material_routes else 0)),
        )
        assignments: list[
            tuple[str, Mapping[str, Any], Mapping[str, Any], str]
        ] = []
        vehicle_candidates = [
            ("vehicle", placement)
            for placement, _ in candidates["vehicle"]
        ]
        equipment_candidates = [
            ("mobile_equipment", placement)
            for placement, _ in candidates["mobile_equipment"]
        ]
        # The paired lanes on the primary material boulevard are vehicle lanes.
        # Keep mobile equipment behind every available vehicle so the first two
        # deterministic slots are forklifts whenever the layout provides them.
        movable_candidates = vehicle_candidates + equipment_candidates
        material_route_slots: list[tuple[Mapping[str, Any], str]] = []
        if material_routes:
            material_route_slots.extend([
                (material_routes[0], "forward"),
                (material_routes[0], "reverse"),
            ])
            material_route_slots.extend(
                (route, "forward" if index % 2 == 0 else "reverse")
                for index, route in enumerate(material_routes[1:])
            )
        for index in range(material_slots):
            actor_type, placement = movable_candidates[index]
            route, direction = material_route_slots[index]
            assignments.append((actor_type, placement, route, direction))
        for index in range(operator_slots):
            placement = candidates["operator"][index][0]
            assignments.append((
                "operator",
                placement,
                operator_routes[index],
                "forward" if index % 2 == 0 else "reverse",
            ))
        if not assignments and not local_operator_plans:
            raise FacilityValidationError(
                "facility_activity_actors_unavailable",
                "No exact placed mobile actors are available for authored or "
                "derived local routes.",
            )
        actors = []
        actor_payloads: dict[str, dict[str, Any]] = {}
        unavailable_activity: list[dict[str, Any]] = []
        lean_operator_paths: list[dict[str, Any]] = []
        lean_paths_by_plan_id: dict[str, dict[str, Any]] = {}
        local_actors_by_plan_id: dict[str, dict[str, Any]] = {}
        local_profiles_by_plan_id: dict[str, dict[str, Any]] = {}
        lean_pedestrian_connections: list[dict[str, Any]] = []
        resolved_fifo_positions: dict[str, dict[str, float]] = {}
        visit_plans_by_plan_id: dict[str, list[Mapping[str, Any]]] = {}
        for visit_plan in lean_blueprint.get("pedestrianLinkPlans", []):
            visit_plans_by_plan_id.setdefault(
                str(visit_plan["planId"]),
                [],
            ).append(visit_plan)
        for visit_plans in visit_plans_by_plan_id.values():
            visit_plans.sort(key=lambda item: str(item["connectionPlanId"]))
        maximum_end = 0.0
        for index, (actor_type, placement, route, direction) in enumerate(
            assignments
        ):
            try:
                asset_ref = {
                    "assetId": str(placement["assetId"]),
                    "assetDefinitionRevision": str(
                        placement["assetDefinitionRevision"]
                    ),
                }
                visual_alignment = activity_visual_alignment(asset_ref)
                built, profile = self._build_prototype_activity_actor_package(
                    principal=principal,
                    site_id=site_id,
                    layout_id=layout_id,
                    draft=draft,
                    active_revision=active_revision,
                    context=context,
                    placement=placement,
                    route=route,
                    actor_type=actor_type,
                    travel_direction=direction,
                )
                movement = built["package"]["movement"]
                duration = self._activity_movement_duration(movement)
                loop_mode = "ping_pong"
                endpoint_turn_seconds = FACILITY_ACTIVITY_ENDPOINT_TURN_SECONDS
                return_package_id = None
                end_transfer_package_id = None
                start_transfer_package_id = None
                package_builds = [built]
                lane_binding = movement.get("laneBinding")
                if (
                    actor_type == "vehicle"
                    and isinstance(lane_binding, Mapping)
                    and lane_binding.get("status") == "direction_markings"
                ):
                    opposite_direction = (
                        "reverse" if direction == "forward" else "forward"
                    )
                    return_built, return_profile = (
                        self._build_prototype_activity_actor_package(
                            principal=principal,
                            site_id=site_id,
                            layout_id=layout_id,
                            draft=draft,
                            active_revision=active_revision,
                            context=context,
                            placement=placement,
                            route=route,
                            actor_type=actor_type,
                            travel_direction=opposite_direction,
                        )
                    )
                    return_movement = return_built["package"]["movement"]
                    return_lane = return_movement.get("laneBinding")
                    if (
                        return_movement.get("outcome") != "accepted"
                        or not isinstance(return_lane, Mapping)
                        or return_lane.get("status") != "direction_markings"
                        or return_lane.get("travelDirection")
                        != opposite_direction
                    ):
                        raise FacilityValidationError(
                            "facility_activity_lane_exchange_unavailable",
                            "The opposite direction-marked lane did not produce "
                            "an accepted return traversal.",
                            details={"routeId": route.get("routeId")},
                        )
                    if (
                        return_profile.get("vehicleProfileRevision")
                        != profile.get("vehicleProfileRevision")
                    ):
                        raise FacilityValidationError(
                            "facility_activity_lane_exchange_unavailable",
                            "The paired lane packages do not share one exact "
                            "vehicle profile revision.",
                        )
                    end_transfer_built = (
                        self._build_prototype_lane_transfer_package(
                            principal=principal,
                            site_id=site_id,
                            layout_id=layout_id,
                            draft=draft,
                            active_revision=active_revision,
                            context=context,
                            placement=placement,
                            route=route,
                            profile=profile,
                            start_movement=movement,
                            goal_movement=return_movement,
                        )
                    )
                    start_transfer_built = (
                        self._build_prototype_lane_transfer_package(
                            principal=principal,
                            site_id=site_id,
                            layout_id=layout_id,
                            draft=draft,
                            active_revision=active_revision,
                            context=context,
                            placement=placement,
                            route=route,
                            profile=profile,
                            start_movement=return_movement,
                            goal_movement=movement,
                        )
                    )
                    return_package_id = return_built["package"]["packageId"]
                    end_transfer_package_id = (
                        end_transfer_built["package"]["packageId"]
                    )
                    start_transfer_package_id = (
                        start_transfer_built["package"]["packageId"]
                    )
                    package_builds.extend([
                        return_built,
                        end_transfer_built,
                        start_transfer_built,
                    ])
                    loop_mode = "paired_lanes"
                    endpoint_turn_seconds = 0.0
                    actor_cycle = sum(
                        self._activity_movement_duration(
                            package_build["package"]["movement"]
                        )
                        for package_build in package_builds
                    )
                else:
                    actor_cycle = (
                        2 * duration
                        + 2 * FACILITY_ACTIVITY_ENDPOINT_TURN_SECONDS
                    )
            except FacilityValidationError as exc:
                unavailable_activity.append({
                    "actorType": actor_type,
                    "placementId": str(placement["placementId"]),
                    "routeId": str(route["routeId"]),
                    "code": str(exc.code),
                    "reason": str(exc.message),
                    "evidenceStatus": "unknown",
                })
                continue
            package_id = built["package"]["packageId"]
            for package_build in package_builds:
                package = package_build["package"]
                actor_payloads[package["packageId"]] = {
                    "package": deepcopy(package),
                    "facilityMotionEnvelope": deepcopy(
                        package_build["facilityMotionEnvelope"]
                    ),
                    "vehicleProfile": deepcopy(profile),
                    "prototypeMode": True,
                    "prototypeLabel": str(profile["prototypeLabel"]),
                }
            start_offset = (
                0.0 if loop_mode == "paired_lanes"
                else round((index % 4) * 1.5, 3)
            )
            maximum_end = max(maximum_end, start_offset + actor_cycle)
            placement_id = str(placement["placementId"])
            display_name = str(
                context.asset_definitions[
                    (
                        str(placement["assetId"]),
                        str(placement["assetDefinitionRevision"]),
                    )
                ].get("displayName")
                or placement.get("assetId")
            )
            actors.append({
                "actorId": f"actor-{index + 1:02d}-{placement_id[3:15]}",
                "actorType": actor_type,
                "label": f"{display_name} {index + 1:02d}",
                "motionPackageId": package_id,
                "returnMotionPackageId": return_package_id,
                "endTransferMotionPackageId": end_transfer_package_id,
                "startTransferMotionPackageId": start_transfer_package_id,
                "cycleMotionPackageIds": [],
                "placementId": placement_id,
                "assetDefinitionRef": asset_ref,
                "routeId": str(route["routeId"]),
                "departmentZoneIds": self._activity_route_department_ids(
                    draft,
                    route,
                ),
                "startOffsetSeconds": start_offset,
                "repeat": True,
                "loopMode": loop_mode,
                "endpointTurnSeconds": endpoint_turn_seconds,
                "visualAlignment": visual_alignment,
            })
        # People are not static machine obstacles in this presentation. Their
        # interactions are deliberately outside scope and are not validated as
        # traffic or staffing evidence.
        local_actor_ids = set(operator_placements)
        placements_by_id = {
            str(item.get("placementId") or ""): item
            for item in draft.get("placements", [])
            if isinstance(item, Mapping) and item.get("placementId")
        }
        zones_by_id = {
            str(item.get("zoneId") or ""): item
            for item in draft.get("zones", [])
            if isinstance(item, Mapping) and item.get("zoneId")
        }
        for local_index, plan in enumerate(local_operator_plans):
            placement = operator_placements[plan["placementId"]]
            placement_id = str(placement["placementId"])
            route_id = str(plan["routeId"])
            try:
                asset_ref = {
                    "assetId": str(placement["assetId"]),
                    "assetDefinitionRevision": str(
                        placement["assetDefinitionRevision"]
                    ),
                }
                visual_alignment = activity_visual_alignment(asset_ref)
                asset_definition = context.asset_definitions[
                    (
                        asset_ref["assetId"],
                        asset_ref["assetDefinitionRevision"],
                    )
                ]
                profile_document, profile_revision = self._prototype_actor_profile(
                    principal,
                    site_id,
                    placement,
                    asset_definition,
                    "operator",
                )
                profile = deepcopy(profile_document)
                profile["vehicleProfileRevision"] = profile_revision
                waypoints = list(plan["waypoints"])
                if (
                    plan.get("pathKind") == "cell_work_loop"
                    and str(plan.get("zoneLabel") or "")
                    .casefold()
                    .startswith("assembly cell ")
                    and plan.get("assignedPlacementIds")
                ):
                    station_cycle = self._activity_station_service_cycle(
                        plan,
                        placements_by_id,
                        context,
                        profile,
                    )
                    if len(station_cycle) >= 3:
                        waypoints = station_cycle
                local_package_builds = []
                for point_index, start in enumerate(waypoints):
                    goal = waypoints[(point_index + 1) % len(waypoints)]
                    try:
                        local_package_builds.append(
                            self._build_prototype_local_operator_segment(
                                principal=principal,
                                site_id=site_id,
                                layout_id=layout_id,
                                draft=draft,
                                active_revision=active_revision,
                                context=context,
                                placement=placement,
                                route_id=route_id,
                                profile=profile,
                                start=start,
                                goal=goal,
                                traversable_boundary=plan["traversableBoundary"],
                                excluded_placement_ids=local_actor_ids,
                            )
                        )
                    except FacilityValidationError:
                        anchor = plan["anchor"]
                        start_is_anchor = (
                            abs(float(start["x"]) - float(anchor["x"])) <= 1.0e-9
                            and abs(float(start["z"]) - float(anchor["z"]))
                            <= 1.0e-9
                        )
                        goal_is_anchor = (
                            abs(float(goal["x"]) - float(anchor["x"])) <= 1.0e-9
                            and abs(float(goal["z"]) - float(anchor["z"]))
                            <= 1.0e-9
                        )
                        if (
                            plan.get("pathKind") != "cell_work_loop"
                            or start_is_anchor
                            or goal_is_anchor
                        ):
                            raise
                        # A central station can separate two otherwise valid
                        # service faces. Return through this operator's existing
                        # home point instead of crossing the station footprint.
                        local_package_builds.extend([
                            self._build_prototype_local_operator_segment(
                                principal=principal,
                                site_id=site_id,
                                layout_id=layout_id,
                                draft=draft,
                                active_revision=active_revision,
                                context=context,
                                placement=placement,
                                route_id=route_id,
                                profile=profile,
                                start=start,
                                goal=anchor,
                                traversable_boundary=plan["traversableBoundary"],
                                excluded_placement_ids=local_actor_ids,
                            ),
                            self._build_prototype_local_operator_segment(
                                principal=principal,
                                site_id=site_id,
                                layout_id=layout_id,
                                draft=draft,
                                active_revision=active_revision,
                                context=context,
                                placement=placement,
                                route_id=route_id,
                                profile=profile,
                                start=anchor,
                                goal=goal,
                                traversable_boundary=plan["traversableBoundary"],
                                excluded_placement_ids=local_actor_ids,
                            ),
                        ])
                departure_candidates = []
                seen_departures: set[tuple[float, float]] = set()
                for package_index, local_built in enumerate(local_package_builds):
                    poses = local_built["package"]["movement"].get("poses", [])
                    if not poses:
                        continue
                    departure = {
                        "x": round(float(poses[-1]["x"]), 6),
                        "z": round(float(poses[-1]["z"]), 6),
                    }
                    key = (departure["x"], departure["z"])
                    if key in seen_departures:
                        continue
                    seen_departures.add(key)
                    departure_candidates.append((package_index, departure))
                visit_package_groups: list[
                    tuple[Mapping[str, Any], list[dict[str, Any]], int]
                ] = []
                for visit_plan in visit_plans_by_plan_id.get(
                    str(plan["planId"]),
                    [],
                ):
                    goal_candidates = self._activity_fifo_goal_candidates(
                        visit_plan,
                        zones_by_id.get(str(visit_plan["zoneId"])),
                        profile,
                    )
                    last_error: FacilityValidationError | None = None
                    selected_visit = False
                    for visit_goal in goal_candidates:
                        candidates = sorted(
                            departure_candidates,
                            key=lambda item: (
                                math.hypot(
                                    item[1]["x"] - float(visit_goal["x"]),
                                    item[1]["z"] - float(visit_goal["z"]),
                                ),
                                item[0],
                                item[1]["x"],
                                item[1]["z"],
                            ),
                        )
                        for package_index, departure in candidates:
                            visit_boundary = self._activity_connection_boundary(
                                departure,
                                visit_goal,
                                visit_plan["traversableBoundary"],
                                corridor_margin=6.0,
                            )
                            try:
                                outbound_visit = (
                                    self._build_prototype_local_operator_segment(
                                        principal=principal,
                                        site_id=site_id,
                                        layout_id=layout_id,
                                        draft=draft,
                                        active_revision=active_revision,
                                        context=context,
                                        placement=placement,
                                        route_id=(
                                            f"{visit_plan['connectionPlanId']}:outbound"
                                        ),
                                        profile=profile,
                                        start=departure,
                                        goal=visit_goal,
                                        traversable_boundary=visit_boundary,
                                        excluded_placement_ids=local_actor_ids,
                                    )
                                )
                                return_visit = (
                                    self._build_prototype_local_operator_segment(
                                        principal=principal,
                                        site_id=site_id,
                                        layout_id=layout_id,
                                        draft=draft,
                                        active_revision=active_revision,
                                        context=context,
                                        placement=placement,
                                        route_id=(
                                            f"{visit_plan['connectionPlanId']}:return"
                                        ),
                                        profile=profile,
                                        start=visit_goal,
                                        goal=departure,
                                        traversable_boundary=visit_boundary,
                                        excluded_placement_ids=local_actor_ids,
                                    )
                                )
                            except FacilityValidationError as exc:
                                last_error = exc
                                continue
                            visit_package_groups.append((
                                visit_plan,
                                [outbound_visit, return_visit],
                                package_index,
                            ))
                            selected_visit = True
                            break
                        if selected_visit:
                            break
                    if not selected_visit:
                        if last_error is not None:
                            raise last_error
                        raise FacilityValidationError(
                            "facility_activity_pedestrian_connection_unavailable",
                            "The operator path has no validated departure point for "
                            "this FIFO handoff.",
                            details={
                                "connectionPlanId": visit_plan["connectionPlanId"]
                            },
                        )
                visits_after_package: dict[int, list[dict[str, Any]]] = {}
                for _, visit_builds, package_index in visit_package_groups:
                    visits_after_package.setdefault(package_index, []).extend(
                        visit_builds
                    )
                package_builds = []
                for package_index, local_built in enumerate(local_package_builds):
                    package_builds.append(local_built)
                    package_builds.extend(visits_after_package.get(package_index, []))
                package_ids = [
                    built["package"]["packageId"]
                    for built in package_builds
                ]
                actor_cycle = sum(
                    self._activity_movement_duration(
                        built["package"]["movement"]
                    )
                    for built in package_builds
                ) + len(package_builds) * 0.45
                actor_index = len(actors) + 1
                actor_id = f"actor-{actor_index:02d}-{placement_id[3:15]}"
                start_offset = round((local_index % 4) * 0.8, 3)
                maximum_end = max(
                    maximum_end,
                    start_offset + actor_cycle,
                )
                for built in package_builds:
                    package = built["package"]
                    actor_payloads[package["packageId"]] = {
                        "package": deepcopy(package),
                        "facilityMotionEnvelope": deepcopy(
                            built["facilityMotionEnvelope"]
                        ),
                        "vehicleProfile": deepcopy(profile),
                        "prototypeMode": True,
                        "prototypeLabel": str(profile["prototypeLabel"]),
                    }
                actors.append({
                    "actorId": actor_id,
                    "actorType": "operator",
                    "label": (
                        f"Operator - {plan['zoneLabel']}"
                        + (
                            f" - Segment {int(plan['segmentIndex']) + 1}/"
                            f"{int(plan['segmentCount'])}"
                            if int(plan["segmentCount"]) > 1
                            else ""
                        )
                    ),
                    "motionPackageId": package_ids[0],
                    "returnMotionPackageId": None,
                    "endTransferMotionPackageId": None,
                    "startTransferMotionPackageId": None,
                    "cycleMotionPackageIds": package_ids,
                    "placementId": placement_id,
                    "assetDefinitionRef": asset_ref,
                    "routeId": route_id,
                    "departmentZoneIds": [str(plan["zoneId"])],
                    "startOffsetSeconds": start_offset,
                    "repeat": True,
                    "loopMode": "closed_path",
                    "endpointTurnSeconds": 0.45,
                    "visualAlignment": visual_alignment,
                })
                centerline_samples: list[dict[str, float]] = []
                for built in local_package_builds:
                    for pose in built["package"]["movement"]["poses"]:
                        point = {
                            "x": round(float(pose["x"]), 6),
                            "z": round(float(pose["z"]), 6),
                        }
                        if (
                            not centerline_samples
                            or point != centerline_samples[-1]
                        ):
                            centerline_samples.append(point)
                if (
                    centerline_samples
                    and centerline_samples[-1] != centerline_samples[0]
                ):
                    centerline_samples.append(deepcopy(centerline_samples[0]))
                centerline = self._simplify_activity_centerline(
                    centerline_samples,
                    closed=True,
                )
                lean_path = {
                    "pathId": str(plan["planId"]),
                    "actorId": actor_id,
                    "zoneId": str(plan["zoneId"]),
                    "pathKind": str(plan["pathKind"]),
                    "segmentIndex": int(plan["segmentIndex"]),
                    "segmentCount": int(plan["segmentCount"]),
                    "assignedPlacementIds": list(
                        plan["assignedPlacementIds"]
                    ),
                    "centerline": centerline,
                    "closed": True,
                    "evidenceStatus": "derived",
                }
                lean_operator_paths.append(lean_path)
                plan_id = str(plan["planId"])
                lean_paths_by_plan_id[plan_id] = lean_path
                local_actors_by_plan_id[plan_id] = actors[-1]
                local_profiles_by_plan_id[plan_id] = profile
                for visit_plan, visit_builds, _ in visit_package_groups:
                    visit_samples: list[dict[str, float]] = []
                    for visit_built in visit_builds:
                        for pose in visit_built["package"]["movement"]["poses"]:
                            point = {
                                "x": round(float(pose["x"]), 6),
                                "z": round(float(pose["z"]), 6),
                            }
                            if not visit_samples or point != visit_samples[-1]:
                                visit_samples.append(point)
                    if visit_samples and visit_samples[-1] != visit_samples[0]:
                        visit_samples.append(deepcopy(visit_samples[0]))
                    visit_centerline = self._simplify_activity_centerline(
                        visit_samples,
                        closed=False,
                    )
                    outbound_poses = visit_builds[0]["package"]["movement"]["poses"]
                    validated_fifo_position = {
                        "x": round(float(outbound_poses[-1]["x"]), 6),
                        "z": round(float(outbound_poses[-1]["z"]), 6),
                    }
                    resolved_fifo_positions[str(visit_plan["pointId"])] = (
                        validated_fifo_position
                    )
                    lean_pedestrian_connections.append({
                        "connectionId": str(visit_plan["connectionPlanId"]),
                        "actorId": actor_id,
                        "pathId": str(lean_path["pathId"]),
                        "zoneId": str(visit_plan["zoneId"]),
                        "fifoPointId": str(visit_plan["pointId"]),
                        "handoffIds": list(visit_plan["handoffIds"]),
                        "role": str(visit_plan["role"]),
                        "motionPackageIds": [
                            visit_built["package"]["packageId"]
                            for visit_built in visit_builds
                        ],
                        "centerline": visit_centerline,
                        "closed": True,
                        "evidenceStatus": "derived",
                    })
            except FacilityValidationError as exc:
                unavailable_activity.append({
                    "actorType": "operator",
                    "placementId": placement_id,
                    "routeId": route_id,
                    "code": str(exc.code),
                    "reason": str(exc.message),
                    "evidenceStatus": "unknown",
                })
        assistance_gates = []
        for plan in lean_blueprint.get("assistanceGatePlans", []):
            participant_plan_ids = list(plan["participantPlanIds"])
            if not all(
                plan_id in lean_paths_by_plan_id
                and plan_id in local_actors_by_plan_id
                for plan_id in participant_plan_ids
            ):
                continue
            first_gate_point, second_gate_point = (
                self._closest_activity_path_points(
                    lean_paths_by_plan_id[participant_plan_ids[0]]["centerline"],
                    lean_paths_by_plan_id[participant_plan_ids[1]]["centerline"],
                )
            )
            if math.hypot(
                first_gate_point["x"] - second_gate_point["x"],
                first_gate_point["z"] - second_gate_point["z"],
            ) > 0.35:
                continue
            gate_position = {
                "x": round(
                    (first_gate_point["x"] + second_gate_point["x"]) / 2.0,
                    6,
                ),
                "z": round(
                    (first_gate_point["z"] + second_gate_point["z"]) / 2.0,
                    6,
                ),
            }
            assistance_gates.append({
                "gateId": str(plan["gatePlanId"]),
                "zoneId": str(plan["zoneId"]),
                "participantPathIds": [
                    lean_paths_by_plan_id[plan_id]["pathId"]
                    for plan_id in participant_plan_ids
                ],
                "participantActorIds": [
                    local_actors_by_plan_id[plan_id]["actorId"]
                    for plan_id in participant_plan_ids
                ],
                "position": gate_position,
                "evidenceStatus": "derived",
            })
        connections_by_id = {
            connection["connectionId"]: connection
            for connection in lean_pedestrian_connections
        }
        resolved_handoffs = []
        for handoff in lean_blueprint.get("materialHandoffs", []):
            from_plan_id = str(handoff["fromPlanId"])
            to_plan_id = str(handoff["toPlanId"])
            from_connection_id = str(handoff["fromConnectionPlanId"])
            to_connection_id = str(handoff["toConnectionPlanId"])
            if (
                from_plan_id not in local_actors_by_plan_id
                or to_plan_id not in local_actors_by_plan_id
                or from_connection_id not in connections_by_id
                or to_connection_id not in connections_by_id
                or str(handoff["fromPointId"]) not in resolved_fifo_positions
                or str(handoff["toPointId"]) not in resolved_fifo_positions
            ):
                continue
            from_fifo_position = resolved_fifo_positions[
                str(handoff["fromPointId"])
            ]
            to_fifo_position = resolved_fifo_positions[
                str(handoff["toPointId"])
            ]
            middle_z = (
                float(from_fifo_position["z"])
                + float(to_fifo_position["z"])
            ) / 2.0
            handoff_centerline = []
            for point in (
                from_fifo_position,
                {
                    "x": float(from_fifo_position["x"]),
                    "z": middle_z,
                },
                {
                    "x": float(to_fifo_position["x"]),
                    "z": middle_z,
                },
                to_fifo_position,
            ):
                normalized_point = {
                    "x": round(float(point["x"]), 6),
                    "z": round(float(point["z"]), 6),
                }
                if not handoff_centerline or normalized_point != handoff_centerline[-1]:
                    handoff_centerline.append(normalized_point)
            resolved_handoffs.append({
                "handoffId": str(handoff["handoffId"]),
                "fromZoneId": str(handoff["fromZoneId"]),
                "toZoneId": str(handoff["toZoneId"]),
                "centerline": handoff_centerline,
                "fromPointId": str(handoff["fromPointId"]),
                "toPointId": str(handoff["toPointId"]),
                "fromPathId": str(
                    lean_paths_by_plan_id[from_plan_id]["pathId"]
                ),
                "toPathId": str(lean_paths_by_plan_id[to_plan_id]["pathId"]),
                "fromActorId": str(
                    local_actors_by_plan_id[from_plan_id]["actorId"]
                ),
                "toActorId": str(
                    local_actors_by_plan_id[to_plan_id]["actorId"]
                ),
                "fromConnectionId": from_connection_id,
                "toConnectionId": to_connection_id,
                "evidenceStatus": "derived",
            })
        resolved_handoff_ids = {
            handoff["handoffId"] for handoff in resolved_handoffs
        }
        pedestrian_connections = []
        for connection in lean_pedestrian_connections:
            handoff_ids = [
                handoff_id
                for handoff_id in connection["handoffIds"]
                if handoff_id in resolved_handoff_ids
            ]
            if not handoff_ids:
                continue
            resolved_connection = deepcopy(connection)
            resolved_connection["handoffIds"] = handoff_ids
            pedestrian_connections.append(resolved_connection)
        resolved_fifo_ids = {
            point_id
            for handoff in resolved_handoffs
            for point_id in (handoff["fromPointId"], handoff["toPointId"])
        }
        resolved_fifo_points = [
            {
                **deepcopy(point),
                "position": deepcopy(resolved_fifo_positions[point["pointId"]]),
            }
            for point in lean_blueprint.get("fifoPoints", [])
            if point["pointId"] in resolved_fifo_ids
        ]
        if not actors:
            raise FacilityValidationError(
                "facility_activity_actors_unroutable",
                "No selected prototype actor produced a replayable route result.",
            )
        selected_ids = {actor["placementId"] for actor in actors}
        stationary_asset_ids: set[str] = set()
        stationary_count = 0
        for placement in draft.get("placements", []):
            if not isinstance(placement, Mapping) or (
                placement.get("placementId") in selected_ids
            ):
                continue
            definition = context.asset_definitions.get((
                str(placement.get("assetId") or ""),
                str(placement.get("assetDefinitionRevision") or ""),
            ))
            category = str(
                definition.get("category") if isinstance(definition, Mapping)
                else ""
            ).casefold()
            asset_id = str(placement.get("assetId") or "")
            if category in {"machines", "automation"} or any(
                token in asset_id
                for token in (
                    "robot",
                    "cnc",
                    "lathe",
                    "grinder",
                    "saw",
                    "edm",
                )
            ):
                stationary_count += 1
                stationary_asset_ids.add(asset_id)
        scenario = build_facility_activity_scenario(
            layout_revision=active_revision,
            label=str(
                request.get("scenarioLabel")
                or "Prototype factory activity"
            ),
            actors=actors,
            cycle_duration_seconds=max(1.0, maximum_end),
            repeat=True,
            lean_motion=build_facility_lean_motion(
                lean_blueprint,
                lean_operator_paths,
                pedestrian_connections=pedestrian_connections,
                assistance_gates=assistance_gates,
                material_handoffs=resolved_handoffs,
                fifo_points=resolved_fifo_points,
            ),
            stationary_evidence={
                "placementCount": stationary_count,
                "assetTypeCount": len(stationary_asset_ids),
                "reason": (
                    "Fixed machinery remains stationary because this layout "
                    "contains no revision-bound machine kinematic tracks."
                ),
                "evidenceStatus": "unknown",
            },
            unavailable_activity=unavailable_activity,
        )
        scenario_id = scenario["scenarioId"]
        self.activity_scenario_store.put(
            scenario_id,
            {
                "tenantId": principal.tenant_id,
                "siteId": site_id,
                "layoutId": layout_id,
                "layoutRevision": active_revision,
                "scenario": scenario,
                "actorPayloads": actor_payloads,
            },
        )
        return {
            "scenarioId": scenario_id,
            "layoutRevision": active_revision,
            "summary": facility_activity_scenario_summary(scenario),
            "fullScenarioPath": (
                f"/api/facility-layouts/{site_id}/{layout_id}/"
                f"activity-scenarios/{scenario_id}"
            ),
        }

    def get_prototype_activity_scenario(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        scenario_id: str,
        *,
        active_revision: str | None = None,
    ) -> dict[str, Any]:
        """Fetch one browser-only scenario through an exact revision gate."""

        require_facility_action(
            principal,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            action="layout.read",
        )
        payload = self.activity_scenario_store.get(scenario_id)
        if (
            payload.get("tenantId") != principal.tenant_id
            or payload.get("siteId") != site_id
            or payload.get("layoutId") != layout_id
        ):
            raise FacilityNotFoundError(
                "facility_activity_scenario_not_found",
                "The Facility activity scenario is unavailable in this context.",
            )
        expected_revision = str(payload.get("layoutRevision") or "")
        if active_revision is None:
            current = self.layout_repository.get_layout(
                principal,
                site_id,
                layout_id,
            )
            active_revision = str(current["revision"])
        if active_revision != expected_revision:
            raise FacilityConflictError(
                "facility_activity_scenario_stale",
                "The layout changed after this activity scenario was generated.",
                details={
                    "scenarioLayoutRevision": expected_revision,
                    "activeLayoutRevision": active_revision,
                },
            )
        result = {
            "scenario": deepcopy(payload["scenario"]),
            "actorPayloads": deepcopy(payload["actorPayloads"]),
            "prototypeMode": True,
            "prototypeLabel": (
                "Prototype multi-actor presentation; operating behavior is "
                "synthetic and fixed-machine kinematics are not inferred"
            ),
        }
        candidate_presentation = payload.get("candidatePresentation")
        if isinstance(candidate_presentation, Mapping):
            result["candidatePresentation"] = deepcopy(
                dict(candidate_presentation)
            )
        return result

    @staticmethod
    def _candidate_placement_id(
        layout: Mapping[str, Any],
        base_revision: str,
        candidate_id: str,
    ) -> str:
        seed = _canonical_value_bytes(
            {
                "baseRevision": base_revision,
                "candidateId": candidate_id,
                "layoutId": layout.get("layoutId"),
            }
        )
        digest = hashlib.sha256(seed).hexdigest()
        used = {
            str(item.get("placementId"))
            for item in layout.get("placements", [])
            if isinstance(item, Mapping)
        }
        for width in (24, 32, 40, 48, 56, 64):
            candidate = f"pl-{digest[:width]}"
            if candidate not in used:
                return candidate
        raise FacilityValidationError(
            "id_allocation_failed",
            "Could not allocate a spatial candidate placement ID.",
        )

    def preview_spatial_candidate(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        request: Mapping[str, Any],
        candidate_id: str,
        *,
        operations: list[Mapping[str, Any]] | None = None,
    ) -> dict[str, Any]:
        normalized = self._candidate_request(request)
        if normalized["targetPlacementId"] is not None:
            raise FacilityValidationError(
                "candidate_move_not_supported",
                "P6 candidate acceptance supports new placements only.",
            )
        prior_operations = list(operations or [])
        candidate_set = self.generate_spatial_candidates(
            principal,
            site_id,
            layout_id,
            base_revision,
            normalized,
            operations=prior_operations,
        )
        candidate = next(
            (
                item
                for item in candidate_set["candidates"]
                if item.get("candidateId") == candidate_id
            ),
            None,
        )
        if candidate is None:
            raise FacilityConflictError(
                "spatial_candidate_stale",
                "Spatial candidate is no longer available.",
                details={"candidateId": candidate_id},
            )
        current = self.layout_repository.get_layout(
            principal,
            site_id,
            layout_id,
        )
        draft = apply_facility_layout_operations(
            current["layout"],
            prior_operations,
            base_revision=base_revision,
        )["document"]
        binding = {
            "candidateId": candidate_id,
            "layoutFingerprint": candidate["layoutFingerprint"],
            "obstacleFingerprint": candidate["obstacleFingerprint"],
            "assetId": normalized["assetId"],
            "assetDefinitionRevision": normalized[
                "assetDefinitionRevision"
            ],
            "requestedPosition": normalized["requestedPosition"],
            "requestedQuaternion": normalized["requestedQuaternion"],
            "enabledFamilies": normalized["enabledFamilies"],
            "maximumCandidates": normalized["maximumCandidates"],
            "spatialEngineVersion": SPATIAL_ENGINE_VERSION,
            "candidatePolicyVersion": CANDIDATE_POLICY_VERSION,
        }
        relationship = deepcopy(candidate.get("snapRelationship") or {})
        relationship["spatialCandidate"] = binding
        operation = {
            "op": "place_asset",
            "placement": {
                "placementId": self._candidate_placement_id(
                    draft,
                    base_revision,
                    candidate_id,
                ),
                "assetId": normalized["assetId"],
                "assetDefinitionRevision": normalized[
                    "assetDefinitionRevision"
                ],
                "transform": deepcopy(candidate["transform"]),
                "positionMode": normalized["positionMode"],
                "snapRelationship": relationship,
                "metadata": normalized["metadata"],
            },
        }
        preview, dependencies = self._prepare_operations(
            principal,
            site_id,
            layout_id,
            base_revision,
            prior_operations + [operation],
        )
        return {
            "baseRevision": base_revision,
            "candidate": deepcopy(candidate),
            "operation": deepcopy(operation),
            "preview": deepcopy(preview),
            "dependencies": dependencies.to_dict(),
        }

    def _verify_spatial_candidate_operations(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        base_layout: Mapping[str, Any],
        base_revision: str,
        operations: list[Mapping[str, Any]],
    ) -> None:
        for index, operation in enumerate(operations):
            if not isinstance(operation, Mapping) or operation.get("op") != "place_asset":
                continue
            placement = operation.get("placement")
            if not isinstance(placement, Mapping):
                continue
            relationship = placement.get("snapRelationship")
            if not isinstance(relationship, Mapping):
                continue
            binding = relationship.get("spatialCandidate")
            if not isinstance(binding, Mapping):
                continue
            prefix = apply_facility_layout_operations(
                base_layout,
                operations[:index],
                base_revision=base_revision,
            )["document"]
            request = {
                key: deepcopy(binding.get(key))
                for key in (
                    "assetId",
                    "assetDefinitionRevision",
                    "requestedPosition",
                    "requestedQuaternion",
                    "enabledFamilies",
                    "maximumCandidates",
                )
            }
            candidate_set = self._candidate_set_for_layout(
                principal,
                site_id,
                prefix,
                request,
            )
            candidate_id = binding.get("candidateId")
            candidate = next(
                (
                    item
                    for item in candidate_set["candidates"]
                    if item.get("candidateId") == candidate_id
                ),
                None,
            )
            if candidate is None:
                raise FacilityConflictError(
                    "spatial_candidate_stale",
                    "Spatial candidate is no longer available.",
                    details={
                        "candidateId": candidate_id,
                        "operationIndex": index,
                    },
                )
            expected_relationship = deepcopy(dict(relationship))
            expected_relationship.pop("spatialCandidate", None)
            if (
                binding.get("layoutFingerprint")
                != candidate.get("layoutFingerprint")
                or binding.get("obstacleFingerprint")
                != candidate.get("obstacleFingerprint")
                or _canonical_value_bytes(placement.get("transform"))
                != _canonical_value_bytes(candidate.get("transform"))
                or _canonical_value_bytes(expected_relationship)
                != _canonical_value_bytes(candidate.get("snapRelationship") or {})
            ):
                raise FacilityConflictError(
                    "spatial_candidate_stale",
                    "Spatial candidate no longer matches current constraints.",
                    details={
                        "candidateId": candidate_id,
                        "operationIndex": index,
                    },
                )

    def validate_layout(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
    ) -> dict[str, Any]:
        dependencies = self.validate_dependencies(
            principal,
            site_id,
            document,
        )
        spatial = self._diagnose_spatial(principal, site_id, document)
        routing = self._diagnose_routing(principal, site_id, document)
        findings = [
            *deepcopy(spatial["findings"]),
            *deepcopy(routing["findings"]),
        ]
        return {
            "valid": bool(spatial["valid"] and routing["valid"]),
            "safetyStatus": spatial["safetyStatus"],
            "findings": findings,
            "metrics": {
                **deepcopy(spatial["metrics"]),
                "routingErrorCount": routing["metrics"]["errorCount"],
                "routingBlockedCount": routing["metrics"]["blockedCount"],
                "routeCount": routing["metrics"]["routeCount"],
                "utilityNetworkCount": routing["metrics"][
                    "utilityNetworkCount"
                ],
                "processBindingCount": routing["metrics"][
                    "processBindingCount"
                ],
            },
            "spatialEngineVersion": spatial["spatialEngineVersion"],
            "routingEngineVersion": routing["routingEngineVersion"],
            "routingDiagnostics": routing,
            "dependencies": dependencies.to_dict(),
        }

    def archive_layout(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
    ) -> dict[str, Any]:
        return self.layout_repository.archive_layout(
            principal,
            site_id,
            layout_id,
            base_revision,
        )

    def set_default_layout(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
    ) -> dict[str, Any]:
        return self.layout_repository.set_default_layout(
            principal,
            site_id,
            layout_id,
        )
