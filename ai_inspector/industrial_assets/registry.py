"""Authorized industrial-asset catalog and readiness repository.

Registry pointers are authoritative. Immutable definition and render-bundle
artifacts are written first, and the canonical registry is replaced last.
Directory scans are never used to discover a published asset.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
import threading
from typing import Any, Iterable, Mapping, Sequence

from .artifacts import (
    ArtifactValidationError,
    build_aabb_proxy_glb,
    validate_render_artifact_sources,
)
from .authority import (
    EvidenceRecord,
    EvidenceValidationResult,
    IndustrialAssetAuthorityError,
    TrustedSourceRegistry,
    validate_evidence_records,
    validate_revision,
    validate_stable_id,
)


VISIBILITY_LEVELS = frozenset(
    {"private", "site_shared", "tenant_shared", "common"}
)
ASSET_STATUSES = frozenset(
    {"draft", "reviewed", "published", "deprecated", "quarantined", "archived"}
)
LICENSE_STATUSES = frozenset(
    {"verified", "restricted", "review_required", "unknown"}
)
CATALOG_READ_ROLES = frozenset(
    {
        "viewer",
        "editor",
        "approver",
        "catalog_curator",
        "authority_curator",
        "admin",
    }
)
CATALOG_PUBLISH_ROLES = frozenset({"catalog_curator", "admin"})
PROTECTED_FIELDS = frozenset(
    {
        "sourcePath",
        "localPath",
        "storageKey",
        "licenseDocumentPath",
        "rawLicenseDocument",
        "internalNotes",
    }
)
REQUIRED_DEFINITION_FIELDS = frozenset(
    {
        "schemaVersion",
        "documentKind",
        "assetId",
        "ownerTenantId",
        "status",
        "displayName",
        "category",
        "sourceRevision",
        "coordinateFrame",
        "geometry",
        "renderingCompatibility",
        "collision",
        "loading",
        "clearances",
        "connectors",
        "utilities",
        "mobility",
        "capabilities",
        "provenance",
        "evidence",
        "unresolvedItems",
        "readiness",
    }
)


class IndustrialAssetCatalogError(RuntimeError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class CatalogValidationError(IndustrialAssetCatalogError):
    pass


class CatalogAuthorizationError(IndustrialAssetCatalogError):
    pass


class CatalogNotFoundError(IndustrialAssetCatalogError):
    """Used for both absent and cross-scope assets to prevent disclosure."""


class CatalogConflictError(IndustrialAssetCatalogError):
    pass


class CatalogIntegrityError(IndustrialAssetCatalogError):
    pass


def _canonical_json_bytes(value: Any) -> bytes:
    try:
        payload = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    except (TypeError, ValueError) as exc:
        raise CatalogValidationError(
            "invalid_catalog_json",
            f"Catalog content is not canonical JSON: {exc}",
        ) from exc
    return (payload + "\n").encode("ascii")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _native_fs_path(path: Path) -> str:
    """Return a Windows extended-length path when the platform needs one."""

    value = os.path.abspath(str(path))
    if os.name != "nt" or value.startswith("\\\\?\\"):
        return value
    if value.startswith("\\\\"):
        return "\\\\?\\UNC\\" + value[2:]
    return "\\\\?\\" + value


def _require_mapping(value: Any, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise CatalogValidationError(
            "invalid_catalog_record",
            f"{field_name} must be an object.",
        )
    return value


def _require_list(value: Any, field_name: str, *, limit: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > limit:
        raise CatalogValidationError(
            "invalid_catalog_record",
            f"{field_name} must be a bounded list.",
        )
    return value


def _reject_protected_fields(value: Any, path: str = "$") -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key) in PROTECTED_FIELDS:
                raise CatalogValidationError(
                    "protected_provenance_field",
                    f"{path}.{key} is server-only provenance.",
                )
            _reject_protected_fields(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_protected_fields(child, f"{path}[{index}]")


def _finite_numbers(value: Any, path: str) -> None:
    if isinstance(value, bool) or value is None or isinstance(value, str):
        return
    if isinstance(value, (int, float)):
        if not math.isfinite(float(value)):
            raise CatalogValidationError(
                "non_finite_asset_geometry",
                f"{path} must be finite.",
            )
        return
    if isinstance(value, Mapping):
        for key, child in value.items():
            _finite_numbers(child, f"{path}.{key}")
        return
    if isinstance(value, list):
        for index, child in enumerate(value):
            _finite_numbers(child, f"{path}[{index}]")


def _collect_evidence_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "evidence":
                if not isinstance(child, list):
                    raise CatalogValidationError(
                        "invalid_evidence_references",
                        "Evidence references must be a list.",
                    )
                refs.update(
                    validate_stable_id(item, "evidence")
                    for item in child
                )
            else:
                refs.update(_collect_evidence_refs(child))
    elif isinstance(value, list):
        for child in value:
            refs.update(_collect_evidence_refs(child))
    return refs


def validate_asset_definition(value: Mapping[str, Any]) -> dict[str, Any]:
    definition = deepcopy(dict(_require_mapping(value, "assetDefinition")))
    missing = REQUIRED_DEFINITION_FIELDS - set(definition)
    if missing:
        raise CatalogValidationError(
            "asset_definition_fields_missing",
            f"Asset definition is missing: {sorted(missing)}.",
        )
    if (
        definition.get("schemaVersion") != 1
        or definition.get("documentKind") != "industrial_asset_definition"
    ):
        raise CatalogValidationError(
            "unsupported_asset_definition",
            "Only industrial asset definition schema version 1 is supported.",
        )
    validate_stable_id(definition.get("assetId"), "assetId")
    validate_stable_id(definition.get("ownerTenantId"), "ownerTenantId")
    validate_stable_id(definition.get("category"), "category")
    validate_revision(definition.get("sourceRevision"), "sourceRevision")
    if definition.get("status") not in ASSET_STATUSES:
        raise CatalogValidationError(
            "invalid_asset_status",
            "Asset status is unsupported.",
        )
    display_name = definition.get("displayName")
    if (
        not isinstance(display_name, str)
        or not display_name.strip()
        or len(display_name) > 120
    ):
        raise CatalogValidationError(
            "invalid_asset_display_name",
            "displayName must be a non-empty label.",
        )
    for key in (
        "coordinateFrame",
        "geometry",
        "renderingCompatibility",
        "collision",
        "loading",
        "utilities",
        "mobility",
        "capabilities",
        "provenance",
        "readiness",
    ):
        _require_mapping(definition.get(key), key)
    for key, limit in (
        ("clearances", 64),
        ("connectors", 128),
        ("evidence", 64),
        ("unresolvedItems", 10000),
    ):
        _require_list(definition.get(key), key, limit=limit)
    validate_revision(
        definition["renderingCompatibility"].get(
            "geometryInterfaceRevision"
        ),
        "geometryInterfaceRevision",
    )
    if (
        definition["renderingCompatibility"].get(
            "renderBundleSchemaVersion"
        )
        != 1
    ):
        raise CatalogValidationError(
            "render_bundle_schema_incompatible",
            "Asset definition requires render-bundle schema version 1.",
        )
    provenance = definition["provenance"]
    if provenance.get("licenseStatus") not in LICENSE_STATUSES:
        raise CatalogValidationError(
            "invalid_license_status",
            "Asset license status is unsupported.",
        )
    _reject_protected_fields(definition)
    _finite_numbers(definition, "$")
    _canonical_json_bytes(definition)
    return definition


def validate_render_bundle(
    value: Mapping[str, Any],
    *,
    asset_id: str,
    geometry_interface_revision: str,
) -> dict[str, Any]:
    bundle = deepcopy(dict(_require_mapping(value, "renderBundle")))
    if (
        bundle.get("schemaVersion") != 1
        or bundle.get("documentKind") != "industrial_asset_render_bundle"
    ):
        raise CatalogValidationError(
            "unsupported_render_bundle",
            "Only industrial render-bundle schema version 1 is supported.",
        )
    if bundle.get("assetId") != asset_id:
        raise CatalogValidationError(
            "render_bundle_asset_mismatch",
            "Render bundle belongs to another asset.",
        )
    if bundle.get("geometryInterfaceRevision") != geometry_interface_revision:
        raise CatalogValidationError(
            "render_bundle_geometry_incompatible",
            "Render bundle geometry interface is incompatible.",
        )
    lods = _require_list(bundle.get("lodArtifacts"), "lodArtifacts", limit=16)
    thumbnail = _require_mapping(bundle.get("thumbnail"), "thumbnail")
    for artifact in [*lods, thumbnail]:
        record = _require_mapping(artifact, "renderArtifact")
        validate_revision(record.get("sha256"), "artifact.sha256")
        length = record.get("byteLength")
        if isinstance(length, bool) or not isinstance(length, int) or length < 0:
            raise CatalogValidationError(
                "invalid_render_artifact",
                "Render artifact byteLength must be non-negative.",
            )
    _reject_protected_fields(bundle)
    _canonical_json_bytes(bundle)
    return bundle


def asset_definition_revision(definition: Mapping[str, Any]) -> str:
    """Hash semantic definition content while excluding render-only state."""

    normalized = validate_asset_definition(definition)
    normalized.pop("assetDefinitionRevision", None)
    normalized.pop("renderBundleRevision", None)
    normalized.pop("readiness", None)
    compatibility = normalized.get("renderingCompatibility")
    if isinstance(compatibility, dict):
        compatibility.pop("artifacts", None)
        compatibility.pop("thumbnail", None)
        compatibility.pop("textures", None)
        compatibility.pop("overviewGeometry", None)
    return _canonical_hash(normalized)


def render_bundle_revision(bundle: Mapping[str, Any]) -> str:
    normalized = deepcopy(dict(_require_mapping(bundle, "renderBundle")))
    normalized.pop("renderBundleRevision", None)
    return _canonical_hash(normalized)


@dataclass(frozen=True)
class CatalogPrincipal:
    principal_id: str
    tenant_id: str
    site_ids: tuple[str, ...]
    roles: tuple[str, ...]

    def __post_init__(self) -> None:
        validate_stable_id(self.principal_id, "principalId")
        validate_stable_id(self.tenant_id, "tenantId")
        sites = tuple(
            sorted(validate_stable_id(item, "siteId") for item in self.site_ids)
        )
        roles = tuple(
            sorted(validate_stable_id(item, "role") for item in self.roles)
        )
        if not sites or len(sites) != len(set(sites)):
            raise CatalogValidationError(
                "invalid_principal_sites",
                "Principal site IDs must be non-empty and unique.",
            )
        if not roles or len(roles) != len(set(roles)):
            raise CatalogValidationError(
                "invalid_principal_roles",
                "Principal roles must be non-empty and unique.",
            )
        object.__setattr__(self, "site_ids", sites)
        object.__setattr__(self, "roles", roles)

    @property
    def role_set(self) -> frozenset[str]:
        return frozenset(self.roles)


@dataclass(frozen=True)
class ReadinessGate:
    value: bool
    blockers: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"value": self.value, "blockers": list(self.blockers)}


@dataclass(frozen=True)
class AssetReadiness:
    visual_ready: ReadinessGate
    placement_ready: ReadinessGate
    planning_ready: ReadinessGate
    public_ready: ReadinessGate

    def to_dict(self) -> dict[str, Any]:
        return {
            "visualReady": self.visual_ready.to_dict(),
            "placementReady": self.placement_ready.to_dict(),
            "planningReady": self.planning_ready.to_dict(),
            "publicReady": self.public_ready.to_dict(),
        }


def _gate(blockers: Iterable[str]) -> ReadinessGate:
    values = tuple(sorted(set(blockers)))
    return ReadinessGate(value=not values, blockers=values)


def _authoritative_refs(
    value: Mapping[str, Any],
    evidence: EvidenceValidationResult,
) -> bool:
    refs = value.get("evidence")
    return bool(
        isinstance(refs, list)
        and refs
        and all(evidence.is_authoritative(item) for item in refs)
    )


def _reviewed_evidenced_items(
    values: Sequence[Mapping[str, Any]],
    evidence: EvidenceValidationResult,
) -> bool:
    return bool(values) and all(
        item.get("evidenceStatus") in {"authored", "derived"}
        and _authoritative_refs(item, evidence)
        for item in values
    )


def compute_asset_readiness(
    definition: Mapping[str, Any],
    render_bundle: Mapping[str, Any] | None,
    evidence: EvidenceValidationResult,
) -> AssetReadiness:
    """Compute effective readiness from content rather than trusting flags."""

    definition = validate_asset_definition(definition)
    visual_blockers: list[str] = []
    if render_bundle is None:
        visual_blockers.extend(
            ["nonblank_compatible_render_bundle_missing", "thumbnail_missing"]
        )
    else:
        bundle = validate_render_bundle(
            render_bundle,
            asset_id=definition["assetId"],
            geometry_interface_revision=definition[
                "renderingCompatibility"
            ]["geometryInterfaceRevision"],
        )
        lods = bundle["lodArtifacts"]
        if not any(
            item.get("byteLength", 0) > 0
            and item.get("nonblank") is True
            and item.get("mediaType") in {
                "model/gltf-binary",
                "model/gltf+json",
            }
            for item in lods
        ):
            visual_blockers.append("nonblank_compatible_render_bundle_missing")
        thumbnail = bundle["thumbnail"]
        if not (
            thumbnail.get("byteLength", 0) > 0
            and thumbnail.get("nonblank") is True
            and thumbnail.get("mediaType") in {
                "image/png",
                "image/webp",
            }
        ):
            visual_blockers.append("thumbnail_missing")

    placement_blockers: list[str] = []
    coordinate = definition["coordinateFrame"]
    matrix = coordinate.get("sourceToCanonical")
    residual = coordinate.get("alignmentResidualMeters")
    frame_valid = (
        isinstance(matrix, list)
        and len(matrix) == 16
        and all(
            not isinstance(item, bool)
            and isinstance(item, (int, float))
            and math.isfinite(float(item))
            for item in matrix
        )
        and coordinate.get("floorAnchor") is not None
        and isinstance(residual, (int, float))
        and not isinstance(residual, bool)
        and 0 <= float(residual) <= 0.001
        and _authoritative_refs(coordinate, evidence)
    )
    if not frame_valid:
        placement_blockers.append("canonical_local_frame_unverified")
    geometry = definition["geometry"]
    if not (
        isinstance(geometry.get("footprintPolygons"), list)
        and geometry["footprintPolygons"]
        and _authoritative_refs(geometry, evidence)
    ):
        placement_blockers.append("footprint_unverified")
    collision = definition["collision"]
    if not (
        collision.get("geometry")
        and collision.get("verticalInterval")
        and _authoritative_refs(collision, evidence)
    ):
        placement_blockers.append("collision_proxy_unverified")

    planning_blockers: list[str] = []
    if placement_blockers:
        planning_blockers.append("placement_not_ready")
    if not _reviewed_evidenced_items(
        definition["clearances"],
        evidence,
    ):
        planning_blockers.append("applicable_clearances_unreviewed")
    if not _reviewed_evidenced_items(
        definition["connectors"],
        evidence,
    ):
        planning_blockers.append("applicable_connectors_unreviewed")
    loading = definition["loading"]
    mass_candidates = [
        loading.get("installedMass"),
        loading.get("operatingMass"),
    ]
    if not any(
        isinstance(item, Mapping)
        and item.get("value") is not None
        and item.get("evidenceStatus") in {"authored", "derived"}
        and _authoritative_refs(item, evidence)
        for item in mass_candidates
    ):
        planning_blockers.append("applicable_loading_unreviewed")

    public_blockers: list[str] = []
    provenance = definition["provenance"]
    if provenance.get("licenseStatus") != "verified":
        public_blockers.append("redistribution_permission_unverified")
    if not provenance.get("attribution"):
        public_blockers.append("required_attribution_missing")
    provenance_refs = provenance.get("evidence")
    states = evidence.state_by_id()
    license_authority = bool(
        isinstance(provenance_refs, list)
        and any(
            states.get(item) is not None
            and states[item].authoritative
            and (
                states[item].claim_key == "industrial_asset.license.redistribution"
                or states[item].claim_key.startswith(
                    "industrial_asset.license.redistribution."
                )
            )
            for item in provenance_refs
        )
    )
    if not license_authority:
        public_blockers.append("redistribution_evidence_unavailable")
    if not provenance.get("sourceLabel"):
        public_blockers.append("safe_client_provenance_missing")

    return AssetReadiness(
        visual_ready=_gate(visual_blockers),
        placement_ready=_gate(placement_blockers),
        planning_ready=_gate(planning_blockers),
        public_ready=_gate(public_blockers),
    )


@dataclass(frozen=True)
class CatalogEntry:
    asset_id: str
    owner_tenant_id: str
    visibility: str
    allowed_site_ids: tuple[str, ...]
    published_asset_definition_revision: str
    default_render_bundle_revision: str
    status: str
    display_name: str
    category: str
    tags: tuple[str, ...]
    readiness: AssetReadiness
    safe_provenance: Mapping[str, Any]
    authority_findings: tuple[Mapping[str, Any], ...]
    intake_job_id: str | None
    checkpoint_fingerprint: str | None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "CatalogEntry":
        visibility = value.get("visibility")
        if visibility not in VISIBILITY_LEVELS:
            raise CatalogIntegrityError(
                "invalid_registry_entry",
                "Registry entry visibility is invalid.",
            )
        readiness = value.get("readiness")
        if not isinstance(readiness, Mapping):
            raise CatalogIntegrityError(
                "invalid_registry_entry",
                "Registry entry readiness is invalid.",
            )

        def parse_gate(name: str) -> ReadinessGate:
            gate = readiness.get(name)
            if (
                not isinstance(gate, Mapping)
                or not isinstance(gate.get("value"), bool)
                or not isinstance(gate.get("blockers"), list)
            ):
                raise CatalogIntegrityError(
                    "invalid_registry_entry",
                    f"Registry readiness gate {name} is invalid.",
                )
            parsed = ReadinessGate(
                gate["value"],
                tuple(
                    sorted(
                        validate_stable_id(item, f"{name}.blockers")
                        for item in gate["blockers"]
                    )
                ),
            )
            if parsed.value is bool(parsed.blockers):
                raise CatalogIntegrityError(
                    "invalid_registry_entry",
                    f"Registry readiness gate {name} is inconsistent.",
                )
            return parsed

        allowed = tuple(
            sorted(
                validate_stable_id(item, "allowedSiteIds")
                for item in value.get("allowedSiteIds", [])
            )
        )
        tags = tuple(
            sorted(validate_stable_id(item, "tags") for item in value.get("tags", []))
        )
        if len(allowed) != len(set(allowed)) or len(tags) != len(set(tags)):
            raise CatalogIntegrityError(
                "invalid_registry_entry",
                "Registry entry lists must not contain duplicates.",
            )
        status = value.get("status")
        if status not in ASSET_STATUSES:
            raise CatalogIntegrityError(
                "invalid_registry_entry",
                "Registry entry status is invalid.",
            )
        display_name = value.get("displayName")
        if (
            not isinstance(display_name, str)
            or not display_name
            or len(display_name) > 120
        ):
            raise CatalogIntegrityError(
                "invalid_registry_entry",
                "Registry entry displayName is invalid.",
            )
        safe_provenance = deepcopy(
            dict(_require_mapping(value.get("safeProvenance"), "safeProvenance"))
        )
        _reject_protected_fields(safe_provenance, "$.safeProvenance")
        intake_job_id = value.get("intakeJobId")
        checkpoint_fingerprint = value.get("checkpointFingerprint")
        if intake_job_id is not None:
            intake_job_id = validate_stable_id(
                intake_job_id,
                "intakeJobId",
            )
        if checkpoint_fingerprint is not None:
            checkpoint_fingerprint = validate_revision(
                checkpoint_fingerprint,
                "checkpointFingerprint",
            )
        if (intake_job_id is None) != (checkpoint_fingerprint is None):
            raise CatalogIntegrityError(
                "invalid_registry_entry",
                "Registry intake binding must be complete.",
            )
        return cls(
            asset_id=validate_stable_id(value.get("assetId"), "assetId"),
            owner_tenant_id=validate_stable_id(
                value.get("ownerTenantId"),
                "ownerTenantId",
            ),
            visibility=visibility,
            allowed_site_ids=allowed,
            published_asset_definition_revision=validate_revision(
                value.get("publishedAssetDefinitionRevision"),
                "publishedAssetDefinitionRevision",
            ),
            default_render_bundle_revision=validate_revision(
                value.get("defaultRenderBundleRevision"),
                "defaultRenderBundleRevision",
            ),
            status=status,
            display_name=display_name,
            category=validate_stable_id(value.get("category"), "category"),
            tags=tags,
            readiness=AssetReadiness(
                parse_gate("visualReady"),
                parse_gate("placementReady"),
                parse_gate("planningReady"),
                parse_gate("publicReady"),
            ),
            safe_provenance=safe_provenance,
            authority_findings=tuple(
                deepcopy(
                    _require_list(
                        value.get("authorityFindings", []),
                        "authorityFindings",
                        limit=10000,
                    )
                )
            ),
            intake_job_id=intake_job_id,
            checkpoint_fingerprint=checkpoint_fingerprint,
        )

    def to_dict(self) -> dict[str, Any]:
        result = {
            "assetId": self.asset_id,
            "ownerTenantId": self.owner_tenant_id,
            "visibility": self.visibility,
            "allowedSiteIds": list(self.allowed_site_ids),
            "publishedAssetDefinitionRevision": (
                self.published_asset_definition_revision
            ),
            "defaultRenderBundleRevision": self.default_render_bundle_revision,
            "status": self.status,
            "displayName": self.display_name,
            "category": self.category,
            "tags": list(self.tags),
            "readiness": self.readiness.to_dict(),
            "safeProvenance": deepcopy(dict(self.safe_provenance)),
            "authorityFindings": [
                deepcopy(dict(item)) for item in self.authority_findings
            ],
        }
        if self.intake_job_id is not None:
            result["intakeJobId"] = self.intake_job_id
            result["checkpointFingerprint"] = self.checkpoint_fingerprint
        return result


@dataclass(frozen=True)
class CatalogPublication:
    entry: CatalogEntry
    registry_revision: str
    asset_definition_revision: str
    render_bundle_revision: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry": self.entry.to_dict(),
            "registryRevision": self.registry_revision,
            "assetDefinitionRevision": self.asset_definition_revision,
            "renderBundleRevision": self.render_bundle_revision,
        }


class IndustrialAssetRegistryRepository:
    """Canonical tenant-scoped catalog with registry-last publication."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    @staticmethod
    def _authorize_site(
        principal: CatalogPrincipal,
        site_id: str,
    ) -> str:
        site_id = validate_stable_id(site_id, "siteId")
        if site_id not in principal.site_ids:
            raise CatalogNotFoundError(
                "catalog_asset_not_found",
                "Catalog asset was not found.",
            )
        return site_id

    @staticmethod
    def _authorize_role(
        principal: CatalogPrincipal,
        allowed: frozenset[str],
        action: str,
    ) -> None:
        if not (principal.role_set & allowed):
            raise CatalogAuthorizationError(
                "catalog_role_not_authorized",
                f"Principal is not authorized for {action}.",
            )

    def _scope_root(self, scope: str) -> Path:
        if scope == "_common":
            return self.root / "_common"
        validate_stable_id(scope, "catalogScope")
        return self.root / scope

    def _registry_path(self, scope: str) -> Path:
        return self._scope_root(scope) / "registry.json"

    @staticmethod
    def _empty_registry(scope: str) -> dict[str, Any]:
        return {
            "schemaVersion": 1,
            "recordKind": "industrial_asset_registry",
            "scope": scope,
            "entries": [],
        }

    def _load_registry(self, scope: str) -> dict[str, Any]:
        path = self._registry_path(scope)
        native_path = _native_fs_path(path)
        if not os.path.exists(native_path):
            return self._empty_registry(scope)
        try:
            with open(native_path, "r", encoding="ascii") as stream:
                value = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CatalogIntegrityError(
                "catalog_registry_unreadable",
                "Catalog registry is unreadable.",
            ) from exc
        if (
            not isinstance(value, dict)
            or value.get("schemaVersion") != 1
            or value.get("recordKind") != "industrial_asset_registry"
            or value.get("scope") != scope
            or not isinstance(value.get("entries"), list)
        ):
            raise CatalogIntegrityError(
                "catalog_registry_invalid",
                "Catalog registry is invalid.",
            )
        try:
            entries = [
                CatalogEntry.from_mapping(item) for item in value["entries"]
            ]
        except (
            CatalogValidationError,
            IndustrialAssetAuthorityError,
        ) as exc:
            raise CatalogIntegrityError(
                "catalog_registry_invalid",
                "Catalog registry contains an invalid entry.",
            ) from exc
        ids = [item.asset_id for item in entries]
        if ids != sorted(ids) or len(ids) != len(set(ids)):
            raise CatalogIntegrityError(
                "catalog_registry_invalid",
                "Catalog entries must be unique and sorted.",
            )
        if scope == "_common":
            if any(
                item.visibility != "common"
                or not item.readiness.public_ready.value
                for item in entries
            ):
                raise CatalogIntegrityError(
                    "catalog_registry_invalid",
                    "Common registry contains a non-public entry.",
                )
        elif any(
            item.owner_tenant_id != scope or item.visibility == "common"
            for item in entries
        ):
            raise CatalogIntegrityError(
                "catalog_registry_invalid",
                "Tenant registry contains a cross-scope entry.",
            )
        return value

    def registry_revision(self, scope: str) -> str:
        return _canonical_hash(self._load_registry(scope))

    @staticmethod
    def _atomic_write(path: Path, payload: bytes) -> None:
        native_parent = _native_fs_path(path.parent)
        native_path = _native_fs_path(path)
        os.makedirs(native_parent, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=native_parent,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary_name, native_path)
        finally:
            try:
                os.unlink(temporary_name)
            except FileNotFoundError:
                pass
            except OSError:
                pass

    @classmethod
    def _write_immutable(cls, path: Path, value: Any) -> None:
        payload = _canonical_json_bytes(value)
        native_path = _native_fs_path(path)
        if os.path.exists(native_path):
            try:
                with open(native_path, "rb") as stream:
                    current = stream.read()
            except OSError as exc:
                raise CatalogIntegrityError(
                    "catalog_artifact_unreadable",
                    "Immutable catalog artifact is unreadable.",
                ) from exc
            if current != payload:
                raise CatalogConflictError(
                    "immutable_catalog_artifact_conflict",
                    "Immutable catalog artifact content differs.",
                )
            return
        cls._atomic_write(path, payload)

    @classmethod
    def _write_immutable_bytes(
        cls,
        path: Path,
        payload: bytes,
        *,
        expected_sha256: str,
    ) -> None:
        if hashlib.sha256(payload).hexdigest() != expected_sha256:
            raise CatalogIntegrityError(
                "catalog_artifact_identity_mismatch",
                "Catalog artifact bytes do not match their identity.",
            )
        native_path = _native_fs_path(path)
        if os.path.exists(native_path):
            try:
                with open(native_path, "rb") as stream:
                    current = stream.read()
            except OSError as exc:
                raise CatalogIntegrityError(
                    "catalog_artifact_unreadable",
                    "Immutable catalog artifact is unreadable.",
                ) from exc
            if current != payload:
                raise CatalogConflictError(
                    "immutable_catalog_artifact_conflict",
                    "Immutable catalog artifact content differs.",
                )
            return
        cls._atomic_write(path, payload)

    @staticmethod
    def _artifact_bytes(
        descriptor: Mapping[str, Any],
        *,
        expected_sha256: str,
    ) -> bytes:
        source = descriptor.get("sourcePath")
        expected_length = descriptor.get("byteLength")
        if not isinstance(source, Path) or not isinstance(
            expected_length,
            int,
        ):
            raise CatalogIntegrityError(
                "catalog_artifact_descriptor_invalid",
                "Validated artifact copy descriptor is invalid.",
            )
        try:
            with open(_native_fs_path(source), "rb") as stream:
                payload = stream.read()
        except OSError as exc:
            raise CatalogIntegrityError(
                "catalog_artifact_unreadable",
                "Validated source artifact could not be copied.",
            ) from exc
        if (
            len(payload) != expected_length
            or hashlib.sha256(payload).hexdigest() != expected_sha256
        ):
            raise CatalogIntegrityError(
                "catalog_artifact_changed",
                "Validated source artifact changed before publication.",
            )
        return payload

    @classmethod
    def _install_render_artifacts(
        cls,
        bundle_root: Path,
        bundle: Mapping[str, Any],
        descriptors: Mapping[str, Mapping[str, Any]],
    ) -> None:
        destinations: list[tuple[str, Path]] = []
        lod_by_id: dict[str, Mapping[str, Any]] = {}
        for index, record in enumerate(bundle["lodArtifacts"]):
            digest = record["sha256"]
            lod_id = record.get("lodId", f"lod{index}")
            lod_by_id[str(lod_id)] = record
            destinations.append(
                (digest, bundle_root / "visuals" / f"lod{index}.glb")
            )
        media_suffix = {
            "image/png": ".png",
            "image/webp": ".webp",
            "image/jpeg": ".jpg",
        }
        thumbnail = bundle["thumbnail"]
        destinations.append(
            (
                thumbnail["sha256"],
                bundle_root
                / "visuals"
                / f"thumbnail{media_suffix[thumbnail['mediaType']]}",
            )
        )
        for index, texture in enumerate(bundle.get("textures", [])):
            destinations.append(
                (
                    texture["sha256"],
                    bundle_root
                    / "visuals"
                    / "textures"
                    / (
                        f"texture-{index:04d}"
                        f"{media_suffix[texture['mediaType']]}"
                    ),
                )
            )
        overview = bundle.get("overviewGeometry")
        if isinstance(overview, Mapping):
            overview_lod = lod_by_id.get(str(overview.get("lodId")))
            if overview_lod is not None:
                destinations.append(
                    (
                        overview_lod["sha256"],
                        bundle_root / "proxies" / "overview.glb",
                    )
                )
        for digest, destination in destinations:
            descriptor = descriptors.get(digest)
            if descriptor is None:
                raise CatalogIntegrityError(
                    "catalog_artifact_descriptor_missing",
                    "A validated artifact copy descriptor is missing.",
                )
            payload = cls._artifact_bytes(
                descriptor,
                expected_sha256=digest,
            )
            cls._write_immutable_bytes(
                destination,
                payload,
                expected_sha256=digest,
            )

    def _write_registry(self, scope: str, registry: Mapping[str, Any]) -> None:
        self._atomic_write(
            self._registry_path(scope),
            _canonical_json_bytes(registry),
        )

    @staticmethod
    def _visibility_allowed(
        principal: CatalogPrincipal,
        site_id: str,
        entry: CatalogEntry,
    ) -> bool:
        if entry.visibility == "common":
            return entry.readiness.public_ready.value
        if principal.tenant_id != entry.owner_tenant_id:
            return False
        if entry.visibility in {"private", "tenant_shared"}:
            return True
        if entry.visibility == "site_shared":
            return site_id in entry.allowed_site_ids
        return False

    @staticmethod
    def _normalize_visibility(
        visibility: str,
        allowed_site_ids: Iterable[str],
        principal: CatalogPrincipal,
    ) -> tuple[str, tuple[str, ...]]:
        if visibility not in VISIBILITY_LEVELS:
            raise CatalogValidationError(
                "invalid_catalog_visibility",
                "Catalog visibility is unsupported.",
            )
        allowed = tuple(
            sorted(validate_stable_id(item, "allowedSiteIds") for item in allowed_site_ids)
        )
        if len(allowed) != len(set(allowed)):
            raise CatalogValidationError(
                "duplicate_allowed_site",
                "allowedSiteIds must be unique.",
            )
        if visibility == "site_shared":
            if not allowed or not set(allowed) <= set(principal.site_ids):
                raise CatalogAuthorizationError(
                    "catalog_site_grant_not_authorized",
                    "A curator may grant only permitted sites.",
                )
        elif allowed:
            raise CatalogValidationError(
                "unexpected_allowed_sites",
                "allowedSiteIds are valid only for site_shared assets.",
            )
        return visibility, allowed

    def publish_asset(
        self,
        principal: CatalogPrincipal,
        *,
        site_id: str,
        definition: Mapping[str, Any],
        render_bundle: Mapping[str, Any],
        artifact_sources: Mapping[str, Path],
        intake_job_id: str,
        checkpoint_fingerprint: str,
        trusted_sources: TrustedSourceRegistry | Mapping[str, Any],
        evidence_records: Sequence[EvidenceRecord | Mapping[str, Any]],
        asserted_actor_roles: Mapping[str, Iterable[str]],
        approved_derivations: Mapping[
            str,
            Iterable[tuple[str, str]],
        ],
        as_of: datetime,
        visibility: str = "private",
        allowed_site_ids: Iterable[str] = (),
        expected_registry_revision: str | None = None,
    ) -> CatalogPublication:
        site_id = self._authorize_site(principal, site_id)
        intake_job_id = validate_stable_id(
            intake_job_id,
            "intakeJobId",
        )
        checkpoint_fingerprint = validate_revision(
            checkpoint_fingerprint,
            "checkpointFingerprint",
        )
        self._authorize_role(
            principal,
            CATALOG_PUBLISH_ROLES,
            "catalog.publish",
        )
        normalized = validate_asset_definition(definition)
        if normalized["ownerTenantId"] != principal.tenant_id:
            raise CatalogNotFoundError(
                "catalog_asset_not_found",
                "Catalog asset was not found.",
            )
        if normalized["status"] not in {"reviewed", "published", "deprecated"}:
            raise CatalogValidationError(
                "asset_not_reviewed",
                "Only reviewed assets may enter the catalog.",
            )
        visibility, allowed = self._normalize_visibility(
            visibility,
            allowed_site_ids,
            principal,
        )
        parsed_evidence = tuple(
            item if isinstance(item, EvidenceRecord) else EvidenceRecord.from_mapping(item)
            for item in evidence_records
        )
        evidence_result = validate_evidence_records(
            trusted_sources,
            parsed_evidence,
            tenant_id=principal.tenant_id,
            site_id=site_id,
            as_of=as_of,
            asserted_actor_roles=asserted_actor_roles,
            approved_derivations=approved_derivations,
            principal_roles=principal.roles,
        )
        referenced = _collect_evidence_refs(normalized)
        available = set(evidence_result.state_by_id())
        if not referenced <= available:
            raise CatalogValidationError(
                "referenced_evidence_missing",
                "Asset definition references unavailable evidence.",
            )
        bundle = validate_render_bundle(
            render_bundle,
            asset_id=normalized["assetId"],
            geometry_interface_revision=normalized[
                "renderingCompatibility"
            ]["geometryInterfaceRevision"],
        )
        try:
            artifact_descriptors = validate_render_artifact_sources(
                bundle,
                artifact_sources,
            )
        except ArtifactValidationError as exc:
            raise CatalogValidationError(exc.code, str(exc)) from exc
        readiness = compute_asset_readiness(
            normalized,
            bundle,
            evidence_result,
        )
        if visibility == "common" and not readiness.public_ready.value:
            raise CatalogValidationError(
                "public_publication_not_ready",
                "Common publication requires verified redistribution licensing.",
            )

        # Persist definition readiness independently from the selected bundle.
        stored_definition = deepcopy(normalized)
        stored_definition["readiness"] = compute_asset_readiness(
            normalized,
            None,
            evidence_result,
        ).to_dict()
        definition_revision = asset_definition_revision(stored_definition)
        bundle_revision = render_bundle_revision(bundle)
        asset_id = normalized["assetId"]
        scope = "_common" if visibility == "common" else principal.tenant_id
        scope_root = self._scope_root(scope)
        definition_root = (
            scope_root
            / "assets"
            / asset_id
            / "definitions"
            / definition_revision
        )
        bundle_root = (
            scope_root
            / "assets"
            / asset_id
            / "render_bundles"
            / bundle_revision
        )
        evidence_document = {
            "schemaVersion": 1,
            "recordKind": "industrial_asset_evidence_snapshot",
            "records": [item.to_dict() for item in parsed_evidence],
            "validation": evidence_result.to_dict(),
        }
        entry = CatalogEntry(
            asset_id=asset_id,
            owner_tenant_id=principal.tenant_id,
            visibility=visibility,
            allowed_site_ids=allowed,
            published_asset_definition_revision=definition_revision,
            default_render_bundle_revision=bundle_revision,
            status=normalized["status"],
            display_name=normalized["displayName"],
            category=normalized["category"],
            tags=tuple(
                sorted(
                    validate_stable_id(item, "tags")
                    for item in normalized.get("tags", [])
                )
            ),
            readiness=readiness,
            safe_provenance=deepcopy(dict(normalized["provenance"])),
            authority_findings=tuple(
                item.to_dict() for item in evidence_result.findings
            ),
            intake_job_id=intake_job_id,
            checkpoint_fingerprint=checkpoint_fingerprint,
        )

        with self._lock:
            registry = self._load_registry(scope)
            current_revision = _canonical_hash(registry)
            if expected_registry_revision is not None:
                validate_revision(
                    expected_registry_revision,
                    "expectedRegistryRevision",
                )
                if expected_registry_revision != current_revision:
                    raise CatalogConflictError(
                        "catalog_registry_revision_conflict",
                        "Catalog registry changed before publication.",
                    )

            # Immutable content is installed before the authoritative pointer.
            self._write_immutable(
                definition_root / "asset.json",
                stored_definition,
            )
            self._write_immutable(
                definition_root / "source_binding.json",
                {
                    "schemaVersion": 1,
                    "recordKind": "industrial_asset_source_binding",
                    "assetId": asset_id,
                    "ownerTenantId": principal.tenant_id,
                    "sourceRevision": normalized["sourceRevision"],
                },
            )
            self._write_immutable(
                definition_root / "geometry.json",
                {
                    "schemaVersion": 1,
                    "recordKind": "industrial_asset_geometry",
                    "assetId": asset_id,
                    "coordinateFrame": normalized["coordinateFrame"],
                    "geometry": normalized["geometry"],
                    "collision": normalized["collision"],
                },
            )
            self._write_immutable(
                definition_root / "placement.json",
                {
                    "schemaVersion": 1,
                    "recordKind": "industrial_asset_placement",
                    "assetId": asset_id,
                    "loading": normalized["loading"],
                    "clearances": normalized["clearances"],
                    "connectors": normalized["connectors"],
                    "utilities": normalized["utilities"],
                    "mobility": normalized["mobility"],
                },
            )
            self._write_immutable(
                definition_root / "capabilities.json",
                {
                    "schemaVersion": 1,
                    "recordKind": "industrial_asset_capabilities",
                    "assetId": asset_id,
                    "capabilities": normalized["capabilities"],
                },
            )
            self._write_immutable(
                definition_root / "provenance.json",
                {
                    "schemaVersion": 1,
                    "recordKind": "industrial_asset_provenance",
                    "assetId": asset_id,
                    "provenance": normalized["provenance"],
                },
            )
            self._write_immutable(
                definition_root / "proxies" / "footprint.json",
                {
                    "schemaVersion": 1,
                    "recordKind": "industrial_asset_footprint",
                    "assetId": asset_id,
                    "footprintPolygons": normalized["geometry"][
                        "footprintPolygons"
                    ],
                },
            )
            self._write_immutable(
                definition_root / "proxies" / "clearances.json",
                {
                    "schemaVersion": 1,
                    "recordKind": "industrial_asset_clearances",
                    "assetId": asset_id,
                    "clearances": normalized["clearances"],
                },
            )
            collision_proxy = build_aabb_proxy_glb(
                normalized["geometry"]["aabb"]
            )
            self._write_immutable_bytes(
                definition_root / "proxies" / "collision.glb",
                collision_proxy,
                expected_sha256=hashlib.sha256(
                    collision_proxy
                ).hexdigest(),
            )
            self._write_immutable(
                definition_root / "evidence.json",
                evidence_document,
            )
            self._install_render_artifacts(
                bundle_root,
                bundle,
                artifact_descriptors,
            )
            self._write_immutable(bundle_root / "manifest.json", bundle)

            entries = {
                item["assetId"]: item for item in registry["entries"]
            }
            entries[asset_id] = entry.to_dict()
            next_registry = {
                "schemaVersion": 1,
                "recordKind": "industrial_asset_registry",
                "scope": scope,
                "entries": [
                    entries[key] for key in sorted(entries)
                ],
            }
            self._write_registry(scope, next_registry)
            next_revision = _canonical_hash(next_registry)

        return CatalogPublication(
            entry=entry,
            registry_revision=next_revision,
            asset_definition_revision=definition_revision,
            render_bundle_revision=bundle_revision,
        )

    def _entry_from_scope(
        self,
        scope: str,
        asset_id: str,
    ) -> CatalogEntry | None:
        asset_id = validate_stable_id(asset_id, "assetId")
        registry = self._load_registry(scope)
        for item in registry["entries"]:
            if item.get("assetId") == asset_id:
                return CatalogEntry.from_mapping(item)
        return None

    def _find_visible_entry(
        self,
        principal: CatalogPrincipal,
        *,
        site_id: str,
        asset_id: str,
        scope: str | None,
    ) -> tuple[str, CatalogEntry]:
        site_id = self._authorize_site(principal, site_id)
        self._authorize_role(principal, CATALOG_READ_ROLES, "catalog.read")
        if scope is not None and scope not in {
            principal.tenant_id,
            "_common",
        }:
            raise CatalogNotFoundError(
                "catalog_asset_not_found",
                "Catalog asset was not found.",
            )
        scopes = (
            (scope,)
            if scope is not None
            else (principal.tenant_id, "_common")
        )
        for candidate_scope in scopes:
            entry = self._entry_from_scope(candidate_scope, asset_id)
            if entry is None:
                continue
            if not self._visibility_allowed(principal, site_id, entry):
                raise CatalogNotFoundError(
                    "catalog_asset_not_found",
                    "Catalog asset was not found.",
                )
            return candidate_scope, entry
        raise CatalogNotFoundError(
            "catalog_asset_not_found",
            "Catalog asset was not found.",
        )

    @staticmethod
    def _project_entry(entry: CatalogEntry) -> dict[str, Any]:
        return {
            "assetId": entry.asset_id,
            "displayName": entry.display_name,
            "category": entry.category,
            "tags": list(entry.tags),
            "status": entry.status,
            "publishedAssetDefinitionRevision": (
                entry.published_asset_definition_revision
            ),
            "defaultRenderBundleRevision": entry.default_render_bundle_revision,
            "readiness": entry.readiness.to_dict(),
            "safeProvenance": deepcopy(dict(entry.safe_provenance)),
        }

    def get_asset(
        self,
        principal: CatalogPrincipal,
        *,
        site_id: str,
        asset_id: str,
        scope: str | None = None,
    ) -> dict[str, Any]:
        _, entry = self._find_visible_entry(
            principal,
            site_id=site_id,
            asset_id=asset_id,
            scope=scope,
        )
        return self._project_entry(entry)

    def get_asset_definition(
        self,
        principal: CatalogPrincipal,
        *,
        site_id: str,
        asset_id: str,
        scope: str | None = None,
    ) -> dict[str, Any]:
        resolved_scope, entry = self._find_visible_entry(
            principal,
            site_id=site_id,
            asset_id=asset_id,
            scope=scope,
        )
        path = (
            self._scope_root(resolved_scope)
            / "assets"
            / entry.asset_id
            / "definitions"
            / entry.published_asset_definition_revision
            / "asset.json"
        )
        try:
            with open(_native_fs_path(path), "r", encoding="ascii") as stream:
                definition = json.load(stream)
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise CatalogIntegrityError(
                "catalog_definition_unreadable",
                "Published catalog definition is unreadable.",
            ) from exc
        _reject_protected_fields(definition)
        if (
            asset_definition_revision(definition)
            != entry.published_asset_definition_revision
        ):
            raise CatalogIntegrityError(
                "catalog_definition_revision_mismatch",
                "Published catalog definition does not match its registry revision.",
            )
        return {
            "assetDefinitionRevision": (
                entry.published_asset_definition_revision
            ),
            "defaultRenderBundleRevision": entry.default_render_bundle_revision,
            "readiness": entry.readiness.to_dict(),
            "definition": definition,
        }

    def list_assets(
        self,
        principal: CatalogPrincipal,
        *,
        site_id: str,
    ) -> list[dict[str, Any]]:
        site_id = self._authorize_site(principal, site_id)
        self._authorize_role(principal, CATALOG_READ_ROLES, "catalog.read")
        visible: dict[str, CatalogEntry] = {}
        for scope in (principal.tenant_id, "_common"):
            registry = self._load_registry(scope)
            for raw in registry["entries"]:
                entry = CatalogEntry.from_mapping(raw)
                if self._visibility_allowed(principal, site_id, entry):
                    visible.setdefault(entry.asset_id, entry)
        return [
            self._project_entry(visible[key]) for key in sorted(visible)
        ]
