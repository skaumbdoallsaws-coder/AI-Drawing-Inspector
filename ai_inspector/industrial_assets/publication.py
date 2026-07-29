"""Transaction-gated publication for the industrial-asset catalog.

The shared transaction kernel owns proposal, approval, replay, and receipt
semantics. The industrial-asset registry remains the sole writer and validator
of catalog definitions, render bundles, evidence, and registry pointers.
"""

from __future__ import annotations

import hashlib
import json
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Protocol, Sequence

from ai_inspector.transactions import (
    ApplyOutcome,
    ApplyRequest,
    ApprovalRecord,
    ApprovalRequest,
    CommitResult,
    ExactBinding,
    JsonReceiptStore,
    MutationPlan,
    PrincipalBinding,
    PreparedRecord,
    ProposalRecord,
    ProposalRequest,
    ReconciliationResult,
    TransactionAuthorizationError,
    TransactionBindingError,
    TransactionKernel,
    TransactionTarget,
    TransactionValidationError,
    VolatileTransactionStore,
    canonical_json_bytes,
)
from ai_inspector.transactions.types import validate_idempotency_key

from .authority import (
    EvidenceRecord,
    EvidenceValidationResult,
    TrustedSource,
    TrustedSourceRegistry,
    validate_evidence_records,
    validate_revision,
    validate_stable_id,
)
from .jobs import (
    IndustrialAssetIntakeJobStore,
    IndustrialAssetJobError,
)
from .registry import (
    CATALOG_PUBLISH_ROLES,
    CatalogAuthorizationError,
    CatalogConflictError,
    CatalogEntry,
    CatalogNotFoundError,
    CatalogPrincipal,
    CatalogPublication,
    CatalogValidationError,
    IndustrialAssetRegistryRepository,
    _native_fs_path,
    asset_definition_revision,
    render_bundle_revision,
    validate_asset_definition,
    validate_render_bundle,
)


CATALOG_ACTION = "publish_asset"
CATALOG_DOMAIN = "industrial-asset-catalog"
COMMON_CATALOG_DOMAIN = "industrial-asset-common"
MAX_EVIDENCE_RECORDS = 10_000
MAX_AUTHORITY_ACTORS = 10_000
MAX_DERIVATION_SCOPES = 1_000

AuthorityClock = Callable[[], datetime]
TransactionClock = Callable[[], float]


def _hash(value: Any) -> str:
    return hashlib.sha256(canonical_json_bytes(value)).hexdigest()


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _require_utc(value: Any) -> datetime:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise CatalogValidationError(
            "invalid_publication_clock",
            "Publication authority time must include a timezone.",
        )
    return value.astimezone(timezone.utc)


def _trusted_source_dict(source: TrustedSource) -> dict[str, Any]:
    return {
        "trustedSourceId": source.trusted_source_id,
        "ownerTenantId": source.owner_tenant_id,
        "sourceType": source.source_type,
        "issuer": source.issuer,
        "status": source.status,
        "permittedClaimScopes": list(source.permitted_claim_scopes),
        "allowedSiteIds": list(source.allowed_site_ids),
        "freshnessPolicy": {
            "maximumAgeDays": source.maximum_age_days,
        },
        "currentRevision": source.current_revision,
        "accessPolicy": {
            "allowedRoles": list(source.allowed_roles),
        },
    }


def _trusted_registry_dict(
    registry: TrustedSourceRegistry,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "documentKind": "trusted_source_registry",
        "tenantId": registry.tenant_id,
        "sources": [
            _trusted_source_dict(item) for item in registry.sources
        ],
    }


def _normalize_actor_roles(
    value: Mapping[str, Iterable[str]],
) -> dict[str, list[str]]:
    if not isinstance(value, Mapping) or len(value) > MAX_AUTHORITY_ACTORS:
        raise CatalogValidationError(
            "invalid_publication_authority",
            "Authority actor roles must be a bounded object.",
        )
    result: dict[str, list[str]] = {}
    for actor, roles in value.items():
        actor_id = validate_stable_id(actor, "assertedActorId")
        if isinstance(roles, (str, bytes, bytearray)):
            raise CatalogValidationError(
                "invalid_publication_authority",
                "Authority actor roles must be a list.",
            )
        normalized = sorted(
            {validate_stable_id(item, "assertedActorRole") for item in roles}
        )
        if len(normalized) > 64:
            raise CatalogValidationError(
                "invalid_publication_authority",
                "Authority actor roles exceed the limit.",
            )
        result[actor_id] = normalized
    return {key: result[key] for key in sorted(result)}


def _normalize_derivations(
    value: Mapping[str, Iterable[tuple[str, str]]],
) -> dict[str, list[list[str]]]:
    if not isinstance(value, Mapping) or len(value) > MAX_DERIVATION_SCOPES:
        raise CatalogValidationError(
            "invalid_publication_authority",
            "Approved derivations must be a bounded object.",
        )
    result: dict[str, list[list[str]]] = {}
    for scope, methods in value.items():
        scope_id = validate_stable_id(scope, "derivationScope")
        if isinstance(methods, (str, bytes, bytearray)):
            raise CatalogValidationError(
                "invalid_publication_authority",
                "Approved derivation methods must be a list.",
            )
        normalized: set[tuple[str, str]] = set()
        for item in methods:
            if (
                not isinstance(item, (tuple, list))
                or len(item) != 2
            ):
                raise CatalogValidationError(
                    "invalid_publication_authority",
                    "Approved derivation method is invalid.",
                )
            normalized.add(
                (
                    validate_stable_id(item[0], "derivationMethodId"),
                    validate_stable_id(item[1], "derivationMethodVersion"),
                )
            )
        if len(normalized) > 256:
            raise CatalogValidationError(
                "invalid_publication_authority",
                "Approved derivation methods exceed the limit.",
            )
        result[scope_id] = [list(item) for item in sorted(normalized)]
    return {key: result[key] for key in sorted(result)}


def _evidence_dicts(
    records: Sequence[EvidenceRecord | Mapping[str, Any]],
) -> tuple[dict[str, Any], ...]:
    if (
        isinstance(records, (str, bytes, bytearray))
        or len(records) > MAX_EVIDENCE_RECORDS
    ):
        raise CatalogValidationError(
            "invalid_publication_evidence",
            "Evidence records must be a bounded sequence.",
        )
    parsed = tuple(
        item
        if isinstance(item, EvidenceRecord)
        else EvidenceRecord.from_mapping(item)
        for item in records
    )
    ids = [item.evidence_id for item in parsed]
    if len(ids) != len(set(ids)):
        raise CatalogValidationError(
            "duplicate_evidence_id",
            "Evidence IDs must be unique.",
        )
    return tuple(
        item.to_dict()
        for item in sorted(parsed, key=lambda record: record.evidence_id)
    )


@dataclass(frozen=True)
class PublicationAuthoritySnapshot:
    """Current trusted evidence supplied by an authoritative server adapter."""

    trusted_sources: TrustedSourceRegistry | Mapping[str, Any]
    evidence_records: Sequence[EvidenceRecord | Mapping[str, Any]]
    asserted_actor_roles: Mapping[str, Iterable[str]]
    approved_derivations: Mapping[
        str,
        Iterable[tuple[str, str]],
    ]

    def __post_init__(self) -> None:
        trusted = (
            self.trusted_sources
            if isinstance(self.trusted_sources, TrustedSourceRegistry)
            else TrustedSourceRegistry.from_mapping(self.trusted_sources)
        )
        object.__setattr__(
            self,
            "trusted_sources",
            _trusted_registry_dict(trusted),
        )
        object.__setattr__(
            self,
            "evidence_records",
            _evidence_dicts(self.evidence_records),
        )
        object.__setattr__(
            self,
            "asserted_actor_roles",
            _normalize_actor_roles(self.asserted_actor_roles),
        )
        object.__setattr__(
            self,
            "approved_derivations",
            _normalize_derivations(self.approved_derivations),
        )

    @property
    def fingerprint(self) -> str:
        return _hash(self.to_dict())

    @property
    def evidence_fingerprint(self) -> str:
        return _hash({"records": list(self.evidence_records)})

    def to_dict(self) -> dict[str, Any]:
        return {
            "trustedSources": deepcopy(dict(self.trusted_sources)),
            "evidenceRecords": [
                deepcopy(dict(item)) for item in self.evidence_records
            ],
            "assertedActorRoles": deepcopy(
                dict(self.asserted_actor_roles)
            ),
            "approvedDerivations": deepcopy(
                dict(self.approved_derivations)
            ),
        }

    def registry_arguments(self) -> dict[str, Any]:
        return {
            "trusted_sources": deepcopy(dict(self.trusted_sources)),
            "evidence_records": [
                deepcopy(dict(item)) for item in self.evidence_records
            ],
            "asserted_actor_roles": deepcopy(
                dict(self.asserted_actor_roles)
            ),
            "approved_derivations": {
                scope: {
                    tuple(method)
                    for method in methods
                }
                for scope, methods in self.approved_derivations.items()
            },
        }


class PublicationAuthorityLoader(Protocol):
    def __call__(
        self,
        tenant_id: str,
        site_id: str,
        asset_id: str,
    ) -> PublicationAuthoritySnapshot:
        ...


@dataclass(frozen=True)
class _PublicationIntent:
    site_id: str
    intake_job_id: str
    checkpoint_fingerprint: str
    definition: Mapping[str, Any]
    render_bundle: Mapping[str, Any]
    visibility: str
    allowed_site_ids: tuple[str, ...]
    expected_registry_revision: str
    idempotency_key: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "site_id",
            validate_stable_id(self.site_id, "siteId"),
        )
        if (
            not isinstance(self.intake_job_id, str)
            or not self.intake_job_id.startswith("iaj-")
        ):
            raise CatalogValidationError(
                "invalid_publication_intent",
                "intakeJobId is invalid.",
            )
        object.__setattr__(
            self,
            "checkpoint_fingerprint",
            validate_revision(
                self.checkpoint_fingerprint,
                "checkpointFingerprint",
            ),
        )
        if not isinstance(self.definition, Mapping):
            raise CatalogValidationError(
                "invalid_publication_intent",
                "Asset definition must be an object.",
            )
        if not isinstance(self.render_bundle, Mapping):
            raise CatalogValidationError(
                "invalid_publication_intent",
                "Render bundle must be an object.",
            )
        object.__setattr__(
            self,
            "definition",
            deepcopy(dict(self.definition)),
        )
        object.__setattr__(
            self,
            "render_bundle",
            deepcopy(dict(self.render_bundle)),
        )
        if self.visibility not in {
            "private",
            "site_shared",
            "tenant_shared",
            "common",
        }:
            raise CatalogValidationError(
                "invalid_catalog_visibility",
                "Catalog visibility is unsupported.",
            )
        normalized_sites = tuple(
            sorted(
                validate_stable_id(item, "allowedSiteIds")
                for item in self.allowed_site_ids
            )
        )
        if len(normalized_sites) != len(set(normalized_sites)):
            raise CatalogValidationError(
                "duplicate_allowed_site",
                "allowedSiteIds must be unique.",
            )
        object.__setattr__(self, "allowed_site_ids", normalized_sites)
        object.__setattr__(
            self,
            "expected_registry_revision",
            validate_revision(
                self.expected_registry_revision,
                "expectedRegistryRevision",
            ),
        )
        object.__setattr__(
            self,
            "idempotency_key",
            validate_idempotency_key(self.idempotency_key),
        )

    @property
    def asset_id(self) -> str:
        value = self.definition.get("assetId")
        return validate_stable_id(value, "assetId")

    @property
    def owner_tenant_id(self) -> str:
        value = self.definition.get("ownerTenantId")
        return validate_stable_id(value, "ownerTenantId")

    @property
    def registry_scope(self) -> str:
        return "_common" if self.visibility == "common" else self.owner_tenant_id

    def to_dict(self) -> dict[str, Any]:
        return {
            "siteId": self.site_id,
            "intakeJobId": self.intake_job_id,
            "checkpointFingerprint": self.checkpoint_fingerprint,
            "definition": deepcopy(dict(self.definition)),
            "renderBundle": deepcopy(dict(self.render_bundle)),
            "visibility": self.visibility,
            "allowedSiteIds": list(self.allowed_site_ids),
            "expectedRegistryRevision": self.expected_registry_revision,
            "idempotencyKey": self.idempotency_key,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "_PublicationIntent":
        if not isinstance(value, Mapping):
            raise CatalogValidationError(
                "invalid_publication_intent",
                "Publication intent is unavailable.",
            )
        allowed = value.get("allowedSiteIds", [])
        if not isinstance(allowed, list):
            raise CatalogValidationError(
                "invalid_publication_intent",
                "allowedSiteIds must be a list.",
            )
        return cls(
            site_id=value.get("siteId"),
            intake_job_id=value.get("intakeJobId"),
            checkpoint_fingerprint=value.get("checkpointFingerprint"),
            definition=value.get("definition"),
            render_bundle=value.get("renderBundle"),
            visibility=value.get("visibility"),
            allowed_site_ids=tuple(allowed),
            expected_registry_revision=value.get(
                "expectedRegistryRevision"
            ),
            idempotency_key=value.get("idempotencyKey"),
        )


@dataclass(frozen=True)
class _PublicationEvaluation:
    intent: _PublicationIntent
    authority: PublicationAuthoritySnapshot
    publication: CatalogPublication
    exact_diff: Mapping[str, Any]
    binding: ExactBinding
    artifact_sources: Mapping[str, Path]
    as_of: datetime


def _transaction_principal(
    principal: CatalogPrincipal,
    session_id: str,
    site_id: str,
) -> PrincipalBinding:
    if not isinstance(session_id, str) or not session_id.strip():
        raise TransactionValidationError(
            "invalid_transaction_principal",
            "sessionId must be a non-empty string.",
        )
    session_fingerprint = hashlib.sha256(
        (session_id.strip() + "\x00" + site_id).encode("utf-8")
    ).hexdigest()[:40]
    return PrincipalBinding(
        principal_id=principal.principal_id,
        session_id=f"site-session:{session_fingerprint}",
    )


def _authorize_publication(
    principal: CatalogPrincipal,
    *,
    site_id: str,
    owner_tenant_id: str,
) -> None:
    site = validate_stable_id(site_id, "siteId")
    if (
        site not in principal.site_ids
        or principal.tenant_id != owner_tenant_id
    ):
        raise CatalogNotFoundError(
            "catalog_asset_not_found",
            "Catalog asset was not found.",
        )
    if not (principal.role_set & CATALOG_PUBLISH_ROLES):
        raise CatalogAuthorizationError(
            "catalog_role_not_authorized",
            "Principal is not authorized for catalog publication.",
        )


def _collect_evidence(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, Mapping):
        for key, child in value.items():
            if key == "evidence" and isinstance(child, list):
                result.update(
                    validate_stable_id(item, "evidence") for item in child
                )
            else:
                result.update(_collect_evidence(child))
    elif isinstance(value, list):
        for child in value:
            result.update(_collect_evidence(child))
    return result


def _hard_evidence_ids(
    definition: Mapping[str, Any],
    *,
    visibility: str,
) -> set[str]:
    result: set[str] = set()
    for field_name in ("coordinateFrame", "geometry", "collision"):
        result.update(_collect_evidence(definition.get(field_name)))
    clearances = definition.get("clearances")
    if isinstance(clearances, list):
        for clearance in clearances:
            if (
                isinstance(clearance, Mapping)
                and clearance.get("enforcement") == "hard"
            ):
                result.update(_collect_evidence(clearance))
    if visibility == "common":
        result.update(_collect_evidence(definition.get("provenance")))
    return result


def _assert_hard_evidence(
    definition: Mapping[str, Any],
    evidence: EvidenceValidationResult,
    *,
    visibility: str,
) -> None:
    states = evidence.state_by_id()
    blocked: dict[str, list[str]] = {}
    for evidence_id in sorted(
        _hard_evidence_ids(definition, visibility=visibility)
    ):
        state = states.get(evidence_id)
        if state is None:
            blocked[evidence_id] = ["evidence_missing"]
        elif not state.authoritative:
            blocked[evidence_id] = list(
                state.blockers or ("evidence_not_authoritative",)
            )
    if blocked:
        raise CatalogValidationError(
            "hard_evidence_not_authoritative",
            (
                "Hard placement or publication evidence is unavailable: "
                + ", ".join(
                    f"{key} ({'/'.join(value)})"
                    for key, value in blocked.items()
                )
            ),
        )


class _PreviewRegistryRepository(IndustrialAssetRegistryRepository):
    """Run the registry publisher against a copied registry without writes."""

    def __init__(
        self,
        source_root: Path,
        *,
        scope: str,
        registry: Mapping[str, Any],
    ) -> None:
        self.root = source_root
        self._lock = threading.RLock()
        self._registries = {scope: deepcopy(dict(registry))}

    def _load_registry(self, scope: str) -> dict[str, Any]:
        known = self._registries.get(scope)
        if known is None:
            return self._empty_registry(scope)
        return deepcopy(known)

    @classmethod
    def _write_immutable(cls, path: Path, value: Any) -> None:
        return None

    @classmethod
    def _write_immutable_bytes(
        cls,
        path: Path,
        payload: bytes,
        *,
        expected_sha256: str,
    ) -> None:
        return None

    def _write_registry(
        self,
        scope: str,
        registry: Mapping[str, Any],
    ) -> None:
        self._registries[scope] = deepcopy(dict(registry))


def _exact_diff(
    publication: CatalogPublication,
    *,
    registry_scope: str,
    evidence_fingerprint: str,
    intake_job_id: str,
    checkpoint_fingerprint: str,
) -> dict[str, Any]:
    return {
        "schemaVersion": 1,
        "action": CATALOG_ACTION,
        "registryScope": registry_scope,
        "assetId": publication.entry.asset_id,
        "ownerTenantId": publication.entry.owner_tenant_id,
        "assetDefinitionRevision": (
            publication.asset_definition_revision
        ),
        "renderBundleRevision": publication.render_bundle_revision,
        "evidenceFingerprint": evidence_fingerprint,
        "intakeJobId": intake_job_id,
        "checkpointFingerprint": checkpoint_fingerprint,
        "resultingRegistryRevision": publication.registry_revision,
        "entry": publication.entry.to_dict(),
    }


def _render_artifact_requirements(
    render_bundle: Mapping[str, Any],
) -> dict[str, int]:
    artifacts: list[Any] = []
    lods = render_bundle.get("lodArtifacts")
    textures = render_bundle.get("textures", [])
    thumbnail = render_bundle.get("thumbnail")
    if isinstance(lods, list):
        artifacts.extend(lods)
    if isinstance(textures, list):
        artifacts.extend(textures)
    artifacts.append(thumbnail)
    requirements: dict[str, int] = {}
    for artifact in artifacts:
        if not isinstance(artifact, Mapping):
            raise CatalogValidationError(
                "invalid_render_artifact",
                "Every render artifact must be an object.",
            )
        digest = validate_revision(
            artifact.get("sha256"),
            "artifact.sha256",
        )
        byte_length = artifact.get("byteLength")
        if (
            isinstance(byte_length, bool)
            or not isinstance(byte_length, int)
            or byte_length < 1
        ):
            raise CatalogValidationError(
                "invalid_render_artifact",
                "Render artifact byteLength must be positive.",
            )
        known = requirements.get(digest)
        if known is not None and known != byte_length:
            raise CatalogValidationError(
                "render_artifact_identity_conflict",
                "One artifact hash is associated with multiple lengths.",
            )
        requirements[digest] = byte_length
    if not requirements:
        raise CatalogValidationError(
            "render_artifact_missing",
            "Publication requires render artifacts.",
        )
    return requirements


def _binding(
    intent: _PublicationIntent,
    publication: CatalogPublication,
    authority: PublicationAuthoritySnapshot,
    exact_diff: Mapping[str, Any],
) -> ExactBinding:
    domain = (
        COMMON_CATALOG_DOMAIN
        if intent.registry_scope == "_common"
        else CATALOG_DOMAIN
    )
    dependency = {
        "assetDefinitionRevision": (
            publication.asset_definition_revision
        ),
        "renderBundleRevision": publication.render_bundle_revision,
        "evidenceFingerprint": authority.evidence_fingerprint,
        "authorityFingerprint": authority.fingerprint,
        "intakeJobId": intent.intake_job_id,
        "checkpointFingerprint": intent.checkpoint_fingerprint,
        "registryScope": intent.registry_scope,
        "siteId": intent.site_id,
        "idempotencyKey": intent.idempotency_key,
    }
    return ExactBinding(
        target=TransactionTarget(
            domain=domain,
            scope_id=intent.owner_tenant_id,
            resource_id=intent.asset_id,
        ),
        base_revision=intent.expected_registry_revision,
        diff_hash=_hash(exact_diff),
        dependency_fingerprint=_hash(dependency),
    )


def _receipt_payload(
    publication: CatalogPublication,
    definition: Mapping[str, Any],
    *,
    registry_scope: str,
    intake_job_id: str,
    checkpoint_fingerprint: str,
) -> dict[str, Any]:
    finding_codes = sorted(
        {
            str(item.get("code"))
            for item in publication.entry.authority_findings
            if isinstance(item, Mapping) and item.get("code")
        }
    )
    unresolved = definition.get("unresolvedItems")
    return {
        "assetId": publication.entry.asset_id,
        "registryScope": registry_scope,
        "registryRevision": publication.registry_revision,
        "assetDefinitionRevision": (
            publication.asset_definition_revision
        ),
        "renderBundleRevision": publication.render_bundle_revision,
        "intakeJobId": intake_job_id,
        "checkpointFingerprint": checkpoint_fingerprint,
        "entry": publication.entry.to_dict(),
        "readiness": publication.entry.readiness.to_dict(),
        "warnings": finding_codes,
        "unresolvedItems": (
            deepcopy(unresolved) if isinstance(unresolved, list) else []
        ),
    }


class IndustrialAssetPublicationAdapter:
    """Domain adapter that regenerates and commits one exact publication."""

    def __init__(
        self,
        *,
        repository: IndustrialAssetRegistryRepository,
        intake_job_store: IndustrialAssetIntakeJobStore,
        principal: CatalogPrincipal,
        site_id: str,
        authority_loader: PublicationAuthorityLoader,
        authority_clock: AuthorityClock = _utc_now,
    ) -> None:
        self.repository = repository
        if not isinstance(
            intake_job_store,
            IndustrialAssetIntakeJobStore,
        ):
            raise CatalogValidationError(
                "invalid_intake_job_store",
                "Publication requires an industrial-asset intake store.",
            )
        self.intake_job_store = intake_job_store
        self.principal = principal
        self.site_id = validate_stable_id(site_id, "siteId")
        self.authority_loader = authority_loader
        self.authority_clock = authority_clock

    def _intake_artifacts(
        self,
        intent: _PublicationIntent,
        definition: Mapping[str, Any],
        render_bundle: Mapping[str, Any],
    ) -> Mapping[str, Path]:
        try:
            candidate = self.intake_job_store.get_publication_candidate(
                intent.intake_job_id
            )
        except IndustrialAssetJobError as exc:
            raise CatalogValidationError(
                "intake_candidate_not_ready",
                "The completed intake candidate is unavailable.",
            ) from exc
        expected = {
            "jobId": intent.intake_job_id,
            "tenantId": self.principal.tenant_id,
            "candidateAssetId": definition["assetId"],
            "candidateDefinitionRevision": asset_definition_revision(
                definition
            ),
            "candidateRenderBundleRevision": render_bundle_revision(
                render_bundle
            ),
            "checkpointFingerprint": intent.checkpoint_fingerprint,
        }
        if any(
            candidate.get(key) != value
            for key, value in expected.items()
        ):
            raise CatalogValidationError(
                "intake_candidate_mismatch",
                "The intake candidate does not match this publication.",
            )
        requirements = _render_artifact_requirements(render_bundle)
        try:
            return self.intake_job_store.resolve_checkpointed_artifacts(
                intent.intake_job_id,
                requirements,
            )
        except IndustrialAssetJobError as exc:
            raise CatalogValidationError(
                "publication_artifact_invalid",
                "A completed intake artifact is unavailable or changed.",
            ) from exc

    def _snapshot(
        self,
        intent: _PublicationIntent,
    ) -> PublicationAuthoritySnapshot:
        value = self.authority_loader(
            intent.owner_tenant_id,
            intent.site_id,
            intent.asset_id,
        )
        if not isinstance(value, PublicationAuthoritySnapshot):
            raise CatalogValidationError(
                "invalid_publication_authority",
                "Authority loader returned an invalid snapshot.",
            )
        return value

    def evaluate(
        self,
        intent: _PublicationIntent,
    ) -> _PublicationEvaluation:
        if intent.site_id != self.site_id:
            raise CatalogNotFoundError(
                "catalog_asset_not_found",
                "Catalog asset was not found.",
            )
        _authorize_publication(
            self.principal,
            site_id=intent.site_id,
            owner_tenant_id=intent.owner_tenant_id,
        )
        definition = validate_asset_definition(intent.definition)
        if definition["ownerTenantId"] != self.principal.tenant_id:
            raise CatalogNotFoundError(
                "catalog_asset_not_found",
                "Catalog asset was not found.",
            )
        render_bundle = validate_render_bundle(
            intent.render_bundle,
            asset_id=definition["assetId"],
            geometry_interface_revision=definition[
                "renderingCompatibility"
            ]["geometryInterfaceRevision"],
        )
        artifact_sources = self._intake_artifacts(
            intent,
            definition,
            render_bundle,
        )
        authority = self._snapshot(intent)
        as_of = _require_utc(self.authority_clock())
        authority_args = authority.registry_arguments()
        evidence = validate_evidence_records(
            authority_args["trusted_sources"],
            authority_args["evidence_records"],
            tenant_id=self.principal.tenant_id,
            site_id=intent.site_id,
            as_of=as_of,
            asserted_actor_roles=authority_args[
                "asserted_actor_roles"
            ],
            approved_derivations=authority_args[
                "approved_derivations"
            ],
            principal_roles=self.principal.roles,
        )
        _assert_hard_evidence(
            definition,
            evidence,
            visibility=intent.visibility,
        )

        scope = intent.registry_scope
        with self.repository._lock:
            registry = deepcopy(self.repository._load_registry(scope))
        preview_repository = _PreviewRegistryRepository(
            self.repository.root,
            scope=scope,
            registry=registry,
        )
        publication = preview_repository.publish_asset(
            self.principal,
            site_id=intent.site_id,
            definition=definition,
            render_bundle=intent.render_bundle,
            artifact_sources=artifact_sources,
            intake_job_id=intent.intake_job_id,
            checkpoint_fingerprint=intent.checkpoint_fingerprint,
            as_of=as_of,
            visibility=intent.visibility,
            allowed_site_ids=intent.allowed_site_ids,
            expected_registry_revision=(
                intent.expected_registry_revision
            ),
            **authority_args,
        )
        exact_diff = _exact_diff(
            publication,
            registry_scope=scope,
            evidence_fingerprint=authority.evidence_fingerprint,
            intake_job_id=intent.intake_job_id,
            checkpoint_fingerprint=intent.checkpoint_fingerprint,
        )
        return _PublicationEvaluation(
            intent=intent,
            authority=authority,
            publication=publication,
            exact_diff=exact_diff,
            binding=_binding(
                intent,
                publication,
                authority,
                exact_diff,
            ),
            artifact_sources=artifact_sources,
            as_of=as_of,
        )

    def regenerate(self, proposal: ProposalRecord) -> MutationPlan:
        payload = proposal.payload.get("intent")
        intent = _PublicationIntent.from_dict(payload)
        evaluation = self.evaluate(intent)
        return MutationPlan(
            binding=evaluation.binding,
            payload={"intent": intent.to_dict()},
        )

    def commit(self, plan: MutationPlan) -> CommitResult:
        intent = _PublicationIntent.from_dict(plan.payload.get("intent"))
        evaluation = self.evaluate(intent)
        if evaluation.binding != plan.binding:
            raise TransactionBindingError(
                "transaction_binding_mismatch",
                "Publication inputs changed after regeneration.",
            )
        authority_args = evaluation.authority.registry_arguments()
        publication = self.repository.publish_asset(
            self.principal,
            site_id=intent.site_id,
            definition=intent.definition,
            render_bundle=intent.render_bundle,
            artifact_sources=evaluation.artifact_sources,
            intake_job_id=intent.intake_job_id,
            checkpoint_fingerprint=intent.checkpoint_fingerprint,
            as_of=evaluation.as_of,
            visibility=intent.visibility,
            allowed_site_ids=intent.allowed_site_ids,
            expected_registry_revision=(
                intent.expected_registry_revision
            ),
            **authority_args,
        )
        if publication.to_dict() != evaluation.publication.to_dict():
            raise CatalogConflictError(
                "catalog_publication_changed",
                "Catalog publication changed during commit.",
            )
        return CommitResult(
            revision=publication.registry_revision,
            payload=_receipt_payload(
                publication,
                intent.definition,
                registry_scope=intent.registry_scope,
                intake_job_id=intent.intake_job_id,
                checkpoint_fingerprint=intent.checkpoint_fingerprint,
            ),
        )

    def _reconcile_scope(self, prepared: PreparedRecord) -> str:
        domain = prepared.binding.target.domain
        if domain == COMMON_CATALOG_DOMAIN:
            return "_common"
        if domain == CATALOG_DOMAIN:
            return prepared.binding.target.scope_id
        raise CatalogValidationError(
            "invalid_publication_target",
            "Prepared publication target is invalid.",
        )

    def _published_state(
        self,
        prepared: PreparedRecord,
    ) -> tuple[CatalogPublication, dict[str, Any], str] | None:
        scope = self._reconcile_scope(prepared)
        asset_id = prepared.binding.target.resource_id
        with self.repository._lock:
            entry = self.repository._entry_from_scope(scope, asset_id)
            registry_revision = self.repository.registry_revision(scope)
            if entry is None:
                return None
            scope_root = self.repository._scope_root(scope)
            definition_root = (
                scope_root
                / "assets"
                / asset_id
                / "definitions"
                / entry.published_asset_definition_revision
            )
            bundle_root = (
                scope_root
                / "assets"
                / asset_id
                / "render_bundles"
                / entry.default_render_bundle_revision
            )
            with open(
                _native_fs_path(definition_root / "asset.json"),
                "r",
                encoding="ascii",
            ) as stream:
                definition = json.load(stream)
            with open(
                _native_fs_path(definition_root / "evidence.json"),
                "r",
                encoding="ascii",
            ) as stream:
                evidence_document = json.load(stream)
            with open(
                _native_fs_path(bundle_root / "manifest.json"),
                "r",
                encoding="ascii",
            ) as stream:
                bundle = json.load(stream)

        if (
            asset_definition_revision(definition)
            != entry.published_asset_definition_revision
            or render_bundle_revision(bundle)
            != entry.default_render_bundle_revision
        ):
            return None
        records = evidence_document.get("records")
        if not isinstance(records, list):
            return None
        evidence_fingerprint = _hash(
            {"records": list(_evidence_dicts(records))}
        )
        publication = CatalogPublication(
            entry=entry,
            registry_revision=registry_revision,
            asset_definition_revision=(
                entry.published_asset_definition_revision
            ),
            render_bundle_revision=entry.default_render_bundle_revision,
        )
        if (
            entry.intake_job_id is None
            or entry.checkpoint_fingerprint is None
        ):
            return None
        exact_diff = _exact_diff(
            publication,
            registry_scope=scope,
            evidence_fingerprint=evidence_fingerprint,
            intake_job_id=entry.intake_job_id,
            checkpoint_fingerprint=entry.checkpoint_fingerprint,
        )
        if _hash(exact_diff) != prepared.binding.diff_hash:
            return None
        return publication, definition, scope

    def reconcile_prepared(
        self,
        prepared: PreparedRecord,
    ) -> ReconciliationResult:
        try:
            published = self._published_state(prepared)
            scope = self._reconcile_scope(prepared)
            current_revision = self.repository.registry_revision(scope)
        except Exception:
            return ReconciliationResult.unknown()
        if published is not None:
            publication, definition, scope = published
            return ReconciliationResult.committed(
                CommitResult(
                    revision=publication.registry_revision,
                    payload=_receipt_payload(
                        publication,
                        definition,
                        registry_scope=scope,
                        intake_job_id=(
                            publication.entry.intake_job_id or ""
                        ),
                        checkpoint_fingerprint=(
                            publication.entry.checkpoint_fingerprint or ""
                        ),
                    ),
                )
            )
        if current_revision == prepared.binding.base_revision:
            return ReconciliationResult.not_committed()
        return ReconciliationResult.unknown()


class IndustrialAssetPublicationService:
    """Public sidecar API for exact, approved catalog publication."""

    def __init__(
        self,
        *,
        repository: IndustrialAssetRegistryRepository,
        intake_job_store: IndustrialAssetIntakeJobStore,
        receipt_store: JsonReceiptStore | str | Path,
        authority_loader: PublicationAuthorityLoader,
        authority_clock: AuthorityClock = _utc_now,
        transaction_clock: TransactionClock = time.time,
        token_factory: Callable[[str], str] | None = None,
        proposal_lifetime_seconds: float = 15 * 60,
        approval_lifetime_seconds: float = 5 * 60,
        state_store: VolatileTransactionStore | None = None,
    ) -> None:
        if not isinstance(repository, IndustrialAssetRegistryRepository):
            raise CatalogValidationError(
                "invalid_catalog_repository",
                "repository must be an industrial-asset registry.",
            )
        if not isinstance(
            intake_job_store,
            IndustrialAssetIntakeJobStore,
        ):
            raise CatalogValidationError(
                "invalid_intake_job_store",
                "Publication requires an industrial-asset intake store.",
            )
        if not callable(authority_loader):
            raise CatalogValidationError(
                "invalid_publication_authority",
                "authorityLoader must be callable.",
            )
        if not callable(authority_clock):
            raise CatalogValidationError(
                "invalid_publication_clock",
                "authorityClock must be callable.",
            )
        durable_store = (
            receipt_store
            if isinstance(receipt_store, JsonReceiptStore)
            else JsonReceiptStore(receipt_store)
        )
        self.repository = repository
        self.intake_job_store = intake_job_store
        self.authority_loader = authority_loader
        self.authority_clock = authority_clock
        kernel_options: dict[str, Any] = {
            "state_store": state_store or VolatileTransactionStore(),
            "receipt_store": durable_store,
            "clock": transaction_clock,
            "proposal_lifetime_seconds": proposal_lifetime_seconds,
            "approval_lifetime_seconds": approval_lifetime_seconds,
        }
        if token_factory is not None:
            kernel_options["token_factory"] = token_factory
        self.kernel = TransactionKernel(**kernel_options)

    @staticmethod
    def _scope(principal: CatalogPrincipal, visibility: str) -> str:
        return "_common" if visibility == "common" else principal.tenant_id

    def current_registry_revision(
        self,
        principal: CatalogPrincipal,
        *,
        site_id: str,
        visibility: str,
    ) -> str:
        _authorize_publication(
            principal,
            site_id=site_id,
            owner_tenant_id=principal.tenant_id,
        )
        return self.repository.registry_revision(
            self._scope(principal, visibility)
        )

    def propose(
        self,
        principal: CatalogPrincipal,
        *,
        session_id: str,
        site_id: str,
        intake_job_id: str,
        definition: Mapping[str, Any],
        render_bundle: Mapping[str, Any],
        visibility: str = "private",
        allowed_site_ids: Iterable[str] = (),
        expected_registry_revision: str | None = None,
        idempotency_key: str,
    ) -> ProposalRecord:
        owner = (
            definition.get("ownerTenantId")
            if isinstance(definition, Mapping)
            else None
        )
        if owner != principal.tenant_id:
            raise CatalogNotFoundError(
                "catalog_asset_not_found",
                "Catalog asset was not found.",
            )
        _authorize_publication(
            principal,
            site_id=site_id,
            owner_tenant_id=principal.tenant_id,
        )
        scope = self._scope(principal, visibility)
        try:
            intake_candidate = (
                self.intake_job_store.get_publication_candidate(
                    intake_job_id
                )
            )
        except IndustrialAssetJobError as exc:
            raise CatalogValidationError(
                "intake_candidate_not_ready",
                "The completed intake candidate is unavailable.",
            ) from exc
        base_revision = (
            expected_registry_revision
            if expected_registry_revision is not None
            else self.repository.registry_revision(scope)
        )
        intent = _PublicationIntent(
            site_id=site_id,
            intake_job_id=intake_job_id,
            checkpoint_fingerprint=intake_candidate[
                "checkpointFingerprint"
            ],
            definition=definition,
            render_bundle=render_bundle,
            visibility=visibility,
            allowed_site_ids=tuple(allowed_site_ids),
            expected_registry_revision=base_revision,
            idempotency_key=idempotency_key,
        )
        adapter = IndustrialAssetPublicationAdapter(
            repository=self.repository,
            intake_job_store=self.intake_job_store,
            principal=principal,
            site_id=site_id,
            authority_loader=self.authority_loader,
            authority_clock=self.authority_clock,
        )
        evaluation = adapter.evaluate(intent)
        proposal = self.kernel.propose(
            ProposalRequest(
                action=CATALOG_ACTION,
                binding=evaluation.binding,
                principal=_transaction_principal(
                    principal,
                    session_id,
                    site_id,
                ),
                payload={"intent": intent.to_dict()},
                public_summary={
                    "exactDiff": deepcopy(dict(evaluation.exact_diff)),
                    "definitionFingerprint": (
                        evaluation.publication.asset_definition_revision
                    ),
                    "renderFingerprint": (
                        evaluation.publication.render_bundle_revision
                    ),
                    "evidenceFingerprint": (
                        evaluation.authority.evidence_fingerprint
                    ),
                },
            )
        )
        return proposal

    def get_preview(
        self,
        proposal_id: str,
        principal: CatalogPrincipal,
        *,
        session_id: str,
        site_id: str,
    ) -> dict[str, Any]:
        _authorize_publication(
            principal,
            site_id=site_id,
            owner_tenant_id=principal.tenant_id,
        )
        proposal = self.kernel.get_proposal(
            proposal_id,
            principal=_transaction_principal(
                principal,
                session_id,
                site_id,
            ),
        )
        return proposal.public_dict()

    def approve(
        self,
        proposal_id: str,
        binding: ExactBinding,
        principal: CatalogPrincipal,
        *,
        session_id: str,
        site_id: str,
        idempotency_key: str,
        explicit_approval: bool,
    ) -> ApprovalRecord:
        _authorize_publication(
            principal,
            site_id=site_id,
            owner_tenant_id=binding.target.scope_id,
        )
        transaction_principal = _transaction_principal(
            principal,
            session_id,
            site_id,
        )
        proposal = self.kernel.get_proposal(
            proposal_id,
            principal=transaction_principal,
        )
        intent = _PublicationIntent.from_dict(
            proposal.payload.get("intent")
        )
        if idempotency_key != intent.idempotency_key:
            raise TransactionBindingError(
                "transaction_request_mismatch",
                "Idempotency key does not match the exact preview.",
            )
        return self.kernel.approve(
            ApprovalRequest(
                proposal_id=proposal_id,
                binding=binding,
                principal=transaction_principal,
                idempotency_key=idempotency_key,
                explicit_approval=explicit_approval,
            )
        )

    def apply(
        self,
        approval_token: str,
        binding: ExactBinding,
        principal: CatalogPrincipal,
        *,
        session_id: str,
        site_id: str,
        idempotency_key: str,
    ) -> ApplyOutcome:
        _authorize_publication(
            principal,
            site_id=site_id,
            owner_tenant_id=binding.target.scope_id,
        )
        adapter = IndustrialAssetPublicationAdapter(
            repository=self.repository,
            intake_job_store=self.intake_job_store,
            principal=principal,
            site_id=site_id,
            authority_loader=self.authority_loader,
            authority_clock=self.authority_clock,
        )
        return self.kernel.apply(
            ApplyRequest(
                approval_token=approval_token,
                binding=binding,
                principal=_transaction_principal(
                    principal,
                    session_id,
                    site_id,
                ),
                idempotency_key=idempotency_key,
            ),
            adapter,
        )

    def get_receipt(self, receipt_id: str) -> dict[str, Any]:
        return self.kernel.get_receipt(receipt_id).to_dict()
