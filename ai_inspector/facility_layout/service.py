"""Principal-bound application service for Facility Layout v1."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Mapping, Optional

from .authority_repository import (
    FacilityShellRepository,
    PolicySetRepository,
    VehicleProfileRepository,
)
from .authorization import FacilityPrincipal, require_facility_action
from .errors import (
    FacilityConflictError,
    FacilityNotFoundError,
    FacilityValidationError,
)
from .operations import apply_facility_layout_operations
from .repository import FacilityLayoutRepository
from .spatial import (
    CANDIDATE_POLICY_VERSION,
    SPATIAL_ENGINE_VERSION,
)
from .spatial_executor import FacilitySpatialExecutor
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
        return
    reported_revision = value.get("revision")
    if reported_revision is None:
        reported_revision = value.get(f"{kind}Revision")
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
    ) -> None:
        self.layout_repository = layout_repository
        self.shell_repository = shell_repository
        self.policy_repository = policy_repository
        self.vehicle_repository = vehicle_repository
        self.asset_definition_resolver = asset_definition_resolver
        self.process_map_resolver = process_map_resolver
        self.evidence_authority_resolver = evidence_authority_resolver
        self.spatial_executor = spatial_executor or FacilitySpatialExecutor()

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
        shell = self.shell_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=shell_ref["shellId"],
            revision=shell_ref["shellRevision"],
        )
        policy_ref = document["policySetRef"]
        policy = self.policy_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=policy_ref["policySetId"],
            revision=policy_ref["policySetRevision"],
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

    def validate_dependencies(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        document: Mapping[str, Any],
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
        shell = self.shell_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=shell_ref["shellId"],
            revision=shell_ref["shellRevision"],
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
        policy = self.policy_repository.get_published(
            principal,
            site_id=site_id,
            authority_id=policy_ref["policySetId"],
            revision=policy_ref["policySetRevision"],
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
            self.vehicle_repository.get_published(
                principal,
                site_id=site_id,
                authority_id=vehicle_id,
                revision=revision,
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
        result = self.layout_repository.create_layout(
            principal,
            site_id,
            document,
            make_default=make_default,
        )
        result["dependencies"] = dependencies.to_dict()
        result["spatialDiagnostics"] = spatial
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
        result = self.layout_repository.save_layout(
            principal,
            site_id,
            layout_id,
            document,
            base_revision,
        )
        result["dependencies"] = dependencies.to_dict()
        result["spatialDiagnostics"] = spatial
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

    def _prepare_operations(
        self,
        principal: FacilityPrincipal,
        site_id: str,
        layout_id: str,
        base_revision: str,
        operations: list[Mapping[str, Any]],
    ) -> tuple[dict[str, Any], FacilityDependencySnapshot]:
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
        return {
            "valid": bool(spatial["valid"]),
            "safetyStatus": spatial["safetyStatus"],
            "findings": deepcopy(spatial["findings"]),
            "metrics": deepcopy(spatial["metrics"]),
            "spatialEngineVersion": spatial["spatialEngineVersion"],
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
