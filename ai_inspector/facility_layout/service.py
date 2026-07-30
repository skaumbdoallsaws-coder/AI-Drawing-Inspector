"""Principal-bound application service for Facility Layout v1."""

from __future__ import annotations

import hashlib
import json
import math
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
)
from .authorization import FacilityPrincipal, require_facility_action
from .errors import (
    FacilityAuthorizationError,
    FacilityConflictError,
    FacilityNotFoundError,
    FacilityValidationError,
)
from .canonical import canonical_layout_bytes
from .operations import apply_facility_layout_operations
from .planner import (
    FACILITY_LAYOUT_ALTERNATIVE_POLICY_VERSION,
    FACILITY_LAYOUT_PLANNER_VERSION,
    FacilityLayoutPlanningError,
    generate_layout_proposals,
    validate_layout_request,
)
from .repository import FacilityLayoutRepository
from .routing import (
    ROUTER_VERSION,
    ROUTING_ENGINE_VERSION,
    generate_connector_candidates,
    plan_forklift_route,
    resolve_endpoint,
    validate_route,
    validate_utility_network,
)
from .spatial import (
    CANDIDATE_POLICY_VERSION,
    SPATIAL_ENGINE_VERSION,
    placement_spatial_records,
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
ProcessMapResolver = Callable[
    [FacilityPrincipal, str, str, str, str],
    Mapping[str, Any] | bool | None,
]
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
        process_map_resolver: Optional[ProcessMapResolver] = None,
        evidence_authority_resolver: Optional[
            EvidenceAuthorityResolver
        ] = None,
        spatial_executor: Optional[FacilitySpatialExecutor] = None,
        transaction_runtime: Optional[
            FacilityLayoutTransactionRuntime
        ] = None,
    ) -> None:
        self.layout_repository = layout_repository
        self.shell_repository = shell_repository
        self.policy_repository = policy_repository
        self.vehicle_repository = vehicle_repository
        self.asset_definition_resolver = asset_definition_resolver
        self.process_map_resolver = process_map_resolver
        self.evidence_authority_resolver = evidence_authority_resolver
        self.spatial_executor = spatial_executor or FacilitySpatialExecutor()
        self.transaction_runtime = (
            transaction_runtime or FacilityLayoutTransactionRuntime()
        )

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
            shell=deepcopy(shell.document),
            policy_set=deepcopy(policy.document),
            asset_definitions=definitions,
            evidence_authority=authority,
        )

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
        if introduced:
            raise FacilityValidationError(
                "spatial_validation_failed",
                "Facility Layout transaction introduces authoritative spatial "
                "constraint violations.",
                details={
                    "safetyStatus": candidate.get("safetyStatus"),
                    "findings": introduced,
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
    ) -> dict[str, Any]:
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
            "baseRevision": base_revision,
            "dependencies": dependencies.to_dict(),
        }

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

    @staticmethod
    def _layout_content_fingerprint(
        document: Mapping[str, Any],
    ) -> str:
        candidate = deepcopy(dict(document))
        # Repository-owned timestamps change during an approved save and are
        # not part of the user-approved spatial content.
        candidate["createdAt"] = "__repository_timestamp__"
        candidate["updatedAt"] = "__repository_timestamp__"
        return hashlib.sha256(canonical_layout_bytes(candidate)).hexdigest()

    @staticmethod
    def _collection_receipt_summary(
        values: Any,
    ) -> dict[str, Any]:
        items = (
            deepcopy(list(values))
            if isinstance(values, list)
            else []
        )
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
        value = (
            deepcopy(dict(diagnostics))
            if isinstance(diagnostics, Mapping)
            else {}
        )
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
        return {
            "dependencies": dependencies.to_dict(),
            "operationResult": cls._compact_operation_result(prepared),
            "spatialDiagnostics": cls._diagnostic_receipt_summary(
                prepared.get("spatialDiagnostics")
            ),
            "routingDiagnostics": cls._diagnostic_receipt_summary(
                prepared.get("routingDiagnostics")
            ),
            "alternativeId": alternative["alternativeId"],
            "strategy": alternative["strategy"],
            "metrics": deepcopy(alternative["metrics"]),
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
                return MutationPlan(
                    binding=regenerated,
                    payload={
                        "alternative": alternative,
                        "prepared": prepared,
                    },
                    recovery=service._proposal_recovery_context(
                        alternative,
                        prepared,
                        dependencies,
                    ),
                )

            def commit(self, plan: MutationPlan) -> CommitResult:
                alternative = plan.payload["alternative"]
                operations = alternative["operations"]
                prepared, dependencies = service._prepare_operations(
                    principal,
                    site_id,
                    layout_id,
                    plan.binding.base_revision,
                    operations,
                    required_action="proposal.apply",
                )
                # The full transaction binding was established during
                # regeneration. Replaying operations must still preserve the
                # exact approved content and diff.
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
                commit_payload = service._proposal_commit_payload(
                    alternative,
                    prepared,
                    dependencies,
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

    def _prepare_operations(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        operations: list[Mapping[str, Any]],
        *,
        required_action: str | None = "layout.edit",
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
        self._require_no_new_spatial_errors(baseline_spatial, spatial)
        operation_result["spatialDiagnostics"] = spatial
        routing = self._diagnose_routing(
            principal,
            site_id,
            operation_result["document"],
        )
        self._require_no_new_routing_errors(baseline_routing, routing)
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
