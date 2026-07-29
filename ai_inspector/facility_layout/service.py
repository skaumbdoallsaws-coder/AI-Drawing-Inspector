"""Principal-bound application service for Facility Layout v1."""

from __future__ import annotations

import hashlib
import json
import math
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Optional

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
from .validate import validate_layout


DependencyResolver = Callable[
    [FacilityPrincipal, str, str, str],
    Mapping[str, Any] | bool | None,
]
ProcessMapResolver = Callable[
    [FacilityPrincipal, str, str, str, str],
    Mapping[str, Any] | bool | None,
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
    ) -> None:
        self.layout_repository = layout_repository
        self.shell_repository = shell_repository
        self.policy_repository = policy_repository
        self.vehicle_repository = vehicle_repository
        self.asset_definition_resolver = asset_definition_resolver
        self.process_map_resolver = process_map_resolver

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
        result = self.layout_repository.create_layout(
            principal,
            site_id,
            document,
            make_default=make_default,
        )
        result["dependencies"] = dependencies.to_dict()
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
        result = self.layout_repository.save_layout(
            principal,
            site_id,
            layout_id,
            document,
            base_revision,
        )
        result["dependencies"] = dependencies.to_dict()
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
        return operation_result, dependencies

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
        return {
            "valid": True,
            "findings": [],
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
