from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import os
from pathlib import Path

from PIL import Image
import pytest

from ai_inspector.industrial_assets.artifacts import (
    build_aabb_proxy_glb,
    build_render_bundle_manifest,
    inspect_glb,
    normalize_web_image,
)
from ai_inspector.industrial_assets.jobs import (
    IndustrialAssetIntakeJobStore,
)
from ai_inspector.industrial_assets.publication import (
    IndustrialAssetPublicationService,
    PublicationAuthoritySnapshot,
)
from ai_inspector.industrial_assets.registry import (
    CatalogAuthorizationError,
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogPrincipal,
    CatalogValidationError,
    IndustrialAssetRegistryRepository,
    asset_definition_revision,
    render_bundle_revision,
)
from ai_inspector.transactions import (
    ExactBinding,
    JsonReceiptStore,
    TransactionAuthorizationError,
    TransactionBindingError,
    TransactionTarget,
)


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
SOURCE_REVISION = "1" * 64
GEOMETRY_REVISION = "2" * 64


def _read_bytes(path: Path) -> bytes:
    native = os.path.abspath(str(path))
    if os.name == "nt" and not native.startswith("\\\\?\\"):
        native = "\\\\?\\" + native
    with open(native, "rb") as stream:
        return stream.read()


class SequentialTokens:
    def __init__(self) -> None:
        self.count = 0

    def __call__(self, prefix: str) -> str:
        self.count += 1
        return f"{prefix}-publication-token-{self.count:04d}"


class MutableAuthority:
    def __init__(self, snapshot: PublicationAuthoritySnapshot) -> None:
        self.snapshot = snapshot
        self.calls: list[tuple[str, str, str]] = []

    def __call__(
        self,
        tenant_id: str,
        site_id: str,
        asset_id: str,
    ) -> PublicationAuthoritySnapshot:
        self.calls.append((tenant_id, site_id, asset_id))
        return self.snapshot


def _principal(
    *,
    principal_id: str = "curator-a",
    tenant_id: str = "tenant-a",
    sites: tuple[str, ...] = ("site-a", "site-b"),
    roles: tuple[str, ...] = ("catalog_curator",),
) -> CatalogPrincipal:
    return CatalogPrincipal(principal_id, tenant_id, sites, roles)


def _trusted_sources(
    *,
    status: str = "active",
    current_revision: str = SOURCE_REVISION,
) -> dict:
    return {
        "schemaVersion": 1,
        "documentKind": "trusted_source_registry",
        "tenantId": "tenant-a",
        "sources": [
            {
                "trustedSourceId": "source-machine-spec",
                "ownerTenantId": "tenant-a",
                "sourceType": "manufacturer_specification",
                "issuer": "Machine Manufacturer",
                "status": status,
                "permittedClaimScopes": [
                    "industrial_asset.geometry",
                    "industrial_asset.clearance",
                    "industrial_asset.connector",
                    "industrial_asset.loading",
                    "industrial_asset.license",
                ],
                "allowedSiteIds": ["site-a", "site-b"],
                "freshnessPolicy": {"maximumAgeDays": 365},
                "currentRevision": current_revision,
                "accessPolicy": {"allowedRoles": []},
            }
        ],
    }


def _evidence(
    evidence_id: str,
    claim_key: str,
    *,
    fingerprint: str | None = None,
    status: str = "authored",
    valid_until: str | None = None,
    revoked_at: str | None = None,
) -> dict:
    result = {
        "schemaVersion": 1,
        "documentKind": "evidence_record",
        "evidenceId": evidence_id,
        "tenantId": "tenant-a",
        "subjectRef": {
            "documentKind": "industrial_asset_definition",
            "assetId": "asset-machine-a",
        },
        "claimKey": claim_key,
        "valueFingerprint": fingerprint or evidence_id[-1] * 64,
        "status": status,
        "sourceRef": {
            "trustedSourceId": "source-machine-spec",
            "sourceRevision": SOURCE_REVISION,
            "locator": f"manufacturer/spec#{evidence_id}",
        },
        "assertedBy": "authority-curator-a",
        "assertedAt": "2026-07-01T00:00:00Z",
        "validFrom": "2026-07-01T00:00:00Z",
        "validUntil": valid_until,
        "revokedAt": revoked_at,
        "revocationReason": "Superseded" if revoked_at else None,
    }
    return result


def _evidence_records() -> list[dict]:
    return [
        _evidence("ev-geometry-3", "industrial_asset.geometry.canonical"),
        _evidence("ev-clearance-4", "industrial_asset.clearance.service"),
        _evidence("ev-connector-5", "industrial_asset.connector.material"),
        _evidence("ev-loading-6", "industrial_asset.loading.installed"),
        _evidence(
            "ev-license-7",
            "industrial_asset.license.redistribution",
        ),
    ]


def _authority(
    *,
    records: list[dict] | None = None,
    trusted_sources: dict | None = None,
) -> PublicationAuthoritySnapshot:
    return PublicationAuthoritySnapshot(
        trusted_sources=trusted_sources or _trusted_sources(),
        evidence_records=records or _evidence_records(),
        asserted_actor_roles={
            "authority-curator-a": ["authority_curator"]
        },
        approved_derivations={},
    )


def _definition(
    *,
    asset_id: str = "asset-machine-a",
    license_status: str = "verified",
) -> dict:
    return {
        "schemaVersion": 1,
        "documentKind": "industrial_asset_definition",
        "assetId": asset_id,
        "ownerTenantId": "tenant-a",
        "status": "reviewed",
        "displayName": "Machine A",
        "familyId": "family-machine",
        "variantId": "variant-a",
        "category": "machine",
        "tags": ["cnc"],
        "sourceRevision": "8" * 64,
        "coordinateFrame": {
            "nativeSourceUnits": "mm",
            "sourceHandedness": "right",
            "sourceUpAxis": "+Y",
            "sourceToCanonical": [
                0.001,
                0,
                0,
                0,
                0,
                0.001,
                0,
                0,
                0,
                0,
                0.001,
                0,
                0,
                0,
                0,
                1,
            ],
            "canonicalLocalOrigin": {"x": 0, "y": 0, "z": 0},
            "floorAnchor": {"x": 0, "y": 0, "z": 0},
            "defaultFacingVector": {"x": 1, "y": 0, "z": 0},
            "allowedMountingSurfaces": ["floor"],
            "alignmentResidualMeters": 0.0001,
            "evidence": ["ev-geometry-3"],
        },
        "geometry": {
            "aabb": {
                "minimum": {"x": -1, "y": 0, "z": -1},
                "maximum": {"x": 1, "y": 2, "z": 1},
            },
            "footprintPolygons": [
                [
                    {"x": -1, "z": -1},
                    {"x": 1, "z": -1},
                    {"x": 1, "z": 1},
                    {"x": -1, "z": 1},
                ]
            ],
            "heightInterval": {"minimumY": 0, "maximumY": 2},
            "selectionBounds": {
                "minimum": {"x": -1, "y": 0, "z": -1},
                "maximum": {"x": 1, "y": 2, "z": 1},
            },
            "evidence": ["ev-geometry-3"],
        },
        "renderingCompatibility": {
            "renderBundleSchemaVersion": 1,
            "geometryInterfaceRevision": GEOMETRY_REVISION,
        },
        "collision": {
            "model": "footprint_2_5d",
            "verticalInterval": {"minimumY": 0, "maximumY": 2},
            "geometry": {"footprintIndex": 0},
            "evidence": ["ev-geometry-3"],
        },
        "loading": {
            "transportMass": {
                "value": 900,
                "unit": "kg",
                "evidenceStatus": "authored",
                "evidence": ["ev-loading-6"],
            },
            "installedMass": {
                "value": 1000,
                "unit": "kg",
                "evidenceStatus": "authored",
                "evidence": ["ev-loading-6"],
            },
            "operatingMass": {
                "value": 1100,
                "unit": "kg",
                "evidenceStatus": "authored",
                "evidence": ["ev-loading-6"],
            },
            "centerOfGravity": {
                "value": {"x": 0, "y": 0.8, "z": 0},
                "unit": "m",
                "evidenceStatus": "authored",
                "evidence": ["ev-loading-6"],
            },
            "contactLoads": [],
            "dynamicLoadFactors": [],
            "anchoringAssumptions": [],
            "evidence": ["ev-loading-6"],
        },
        "clearances": [
            {
                "clearanceId": "clearance-service",
                "clearanceKind": "service",
                "geometry": {"shape": "rectangle"},
                "enforcement": "advisory",
                "evidenceStatus": "authored",
                "evidence": ["ev-clearance-4"],
            }
        ],
        "connectors": [
            {
                "connectorId": "material-in",
                "connectorKind": "material",
                "position": {"x": -1, "y": 0.8, "z": 0},
                "facing": {"x": -1, "y": 0, "z": 0},
                "role": "input",
                "interface": {},
                "evidenceStatus": "authored",
                "evidence": ["ev-connector-5"],
            }
        ],
        "utilities": {},
        "mobility": {
            "classification": "static",
            "footprint": None,
            "heading": None,
            "turningRadius": None,
            "speedLimits": {},
            "loadLimits": {},
            "evidence": ["ev-geometry-3"],
        },
        "capabilities": {"processTypes": ["milling"]},
        "provenance": {
            "sourceLabel": "Manufacturer machine specification",
            "vendor": "Machine Manufacturer",
            "model": "Model A",
            "sourceUrl": "https://example.invalid/model-a",
            "licenseStatus": license_status,
            "attribution": "Machine Manufacturer, Model A",
            "evidence": ["ev-license-7"],
        },
        "evidence": [
            "ev-geometry-3",
            "ev-clearance-4",
            "ev-connector-5",
            "ev-loading-6",
            "ev-license-7",
        ],
        "unresolvedItems": [],
        "readiness": {
            "visualReady": {"value": False, "blockers": []},
            "placementReady": {"value": False, "blockers": []},
            "planningReady": {"value": False, "blockers": []},
            "publicReady": {"value": False, "blockers": []},
        },
    }


def _render_data(
    *,
    asset_id: str = "asset-machine-a",
    variant: int = 0,
) -> tuple[dict, dict[str, bytes]]:
    glb_data = build_aabb_proxy_glb(
        {
            "minimum": {"x": -1.0, "y": 0.0, "z": -1.0},
            "maximum": {
                "x": 1.0 + variant * 0.25,
                "y": 2.0,
                "z": 1.0,
            },
        }
    )
    glb = inspect_glb(glb_data)
    image = Image.new("RGB", (48, 32), "white")
    color = (40 + variant * 20, 120, 180 - variant * 20)
    for x in range(8, 40):
        for y in range(6, 26):
            image.putpixel((x, y), color)
    raw_image = io.BytesIO()
    image.save(raw_image, format="PNG")
    thumbnail = normalize_web_image(raw_image.getvalue())
    bundle = dict(
        build_render_bundle_manifest(
            asset_id=asset_id,
            geometry_interface_revision=GEOMETRY_REVISION,
            lods={"lod0": glb},
            overview_lod="lod0",
            thumbnail=thumbnail,
        ).manifest
    )
    return bundle, {
        glb.sha256: glb_data,
        str(thumbnail.manifest["sha256"]): thumbnail.data,
    }


def _service(
    repository: IndustrialAssetRegistryRepository,
    authority: MutableAuthority,
    receipt_root,
    *,
    token_factory=None,
) -> IndustrialAssetPublicationService:
    receipt_store = (
        receipt_root
        if isinstance(receipt_root, JsonReceiptStore)
        else JsonReceiptStore(receipt_root)
    )
    intake_store = IndustrialAssetIntakeJobStore(
        receipt_store.root.parent / "intake",
        stages=("publication",),
    )
    return IndustrialAssetPublicationService(
        repository=repository,
        intake_job_store=intake_store,
        receipt_store=receipt_store,
        authority_loader=authority,
        authority_clock=lambda: NOW,
        transaction_clock=lambda: 1000.0,
        token_factory=token_factory or SequentialTokens(),
    )


def _prepare_intake(
    service: IndustrialAssetPublicationService,
    definition: dict,
    bundle: dict,
    artifacts: dict[str, bytes],
    *,
    complete: bool = True,
    candidate_definition_revision: str | None = None,
    candidate_render_bundle_revision: str | None = None,
) -> str:
    revision = render_bundle_revision(bundle)
    job = service.intake_job_store.create_job(
        {
            "tenantId": definition["ownerTenantId"],
            "requestedBy": "curator-a",
            "sourceFingerprint": hashlib.sha256(
                (definition["assetId"] + ":source").encode("ascii")
            ).hexdigest(),
            "requestedRoot": f"{definition['assetId']}.SLDASM",
            "configuration": "Default",
            "extractionInputs": {
                "extractor": "publication-test",
                "extractorVersion": "1",
            },
        },
        idempotency_key=f"publication-intake-{revision[:20]}",
    )
    if job["status"] == "completed":
        return str(job["jobId"])
    service.intake_job_store.start_job(job["jobId"])
    output_paths = []
    for index, digest in enumerate(sorted(artifacts)):
        relative_path = f"publication/artifact-{index:04d}.bin"
        target = (
            service.intake_job_store.staging_directory(job["jobId"])
            / relative_path
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(artifacts[digest])
        output_paths.append(relative_path)
    service.intake_job_store.checkpoint_stage(
        job["jobId"],
        "publication",
        output_paths=output_paths,
        metadata={"renderBundleRevision": revision},
    )
    if complete:
        service.intake_job_store.complete_job(
            job["jobId"],
            candidate_asset_id=definition["assetId"],
            candidate_definition_revision=(
                candidate_definition_revision
                or asset_definition_revision(definition)
            ),
            candidate_render_bundle_revision=(
                candidate_render_bundle_revision or revision
            ),
        )
    return str(job["jobId"])


def _propose(
    service: IndustrialAssetPublicationService,
    *,
    principal: CatalogPrincipal | None = None,
    session_id: str = "session-a",
    definition: dict | None = None,
    variant: int = 0,
    intake_job_id: str | None = None,
    bundle: dict | None = None,
    artifacts: dict[str, bytes] | None = None,
    visibility: str = "private",
    expected_registry_revision: str | None = None,
    idempotency_key: str = "publication-idem-0001",
):
    selected_definition = definition or _definition()
    if bundle is None or artifacts is None:
        bundle, artifacts = _render_data(
            asset_id=selected_definition["assetId"],
            variant=variant,
        )
    if intake_job_id is None:
        intake_job_id = _prepare_intake(
            service,
            selected_definition,
            bundle,
            artifacts,
        )
    return service.propose(
        principal or _principal(),
        session_id=session_id,
        site_id="site-a",
        intake_job_id=intake_job_id,
        definition=selected_definition,
        render_bundle=bundle,
        visibility=visibility,
        expected_registry_revision=expected_registry_revision,
        idempotency_key=idempotency_key,
    )


def _approve(
    service: IndustrialAssetPublicationService,
    proposal,
    *,
    principal: CatalogPrincipal | None = None,
    session_id: str = "session-a",
    idempotency_key: str = "publication-idem-0001",
):
    return service.approve(
        proposal.proposal_id,
        proposal.binding,
        principal or _principal(),
        session_id=session_id,
        site_id="site-a",
        idempotency_key=idempotency_key,
        explicit_approval=True,
    )


def _apply(
    service: IndustrialAssetPublicationService,
    proposal,
    approval,
    *,
    principal: CatalogPrincipal | None = None,
    session_id: str = "session-a",
    idempotency_key: str = "publication-idem-0001",
):
    return service.apply(
        approval.approval_token,
        proposal.binding,
        principal or _principal(),
        session_id=session_id,
        site_id="site-a",
        idempotency_key=idempotency_key,
    )


def test_successful_publication_has_exact_preview_and_structured_receipt(
    tmp_path,
):
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    authority = MutableAuthority(_authority())
    service = _service(
        repository,
        authority,
        tmp_path / "receipts",
    )
    proposal = _propose(service)
    preview = service.get_preview(
        proposal.proposal_id,
        _principal(),
        session_id="session-a",
        site_id="site-a",
    )
    summary = preview["summary"]
    assert summary["definitionFingerprint"] == (
        summary["exactDiff"]["assetDefinitionRevision"]
    )
    assert summary["renderFingerprint"] == (
        summary["exactDiff"]["renderBundleRevision"]
    )
    assert summary["evidenceFingerprint"] == (
        summary["exactDiff"]["evidenceFingerprint"]
    )
    assert preview["baseRevision"] == repository.registry_revision(
        "tenant-a"
    )

    approval = _approve(service, proposal)
    outcome = _apply(service, proposal, approval)
    receipt = outcome.receipt
    assert receipt.payload["assetId"] == "asset-machine-a"
    assert receipt.payload["registryScope"] == "tenant-a"
    assert receipt.payload["registryRevision"] == receipt.revision
    assert receipt.payload["readiness"]["visualReady"]["value"] is True
    assert receipt.payload["warnings"] == []
    assert repository.get_asset(
        _principal(roles=("viewer",)),
        site_id="site-a",
        asset_id="asset-machine-a",
    )["assetId"] == "asset-machine-a"
    assert service.get_receipt(receipt.receipt_id)["receiptId"] == (
        receipt.receipt_id
    )
    committed_bundle, _ = _render_data()
    bundle_root = (
        repository.root
        / "tenant-a"
        / "assets"
        / "asset-machine-a"
        / "render_bundles"
        / receipt.payload["renderBundleRevision"]
    )
    expected_visuals = {
        bundle_root / "visuals" / "lod0.glb": committed_bundle[
            "lodArtifacts"
        ][0]["sha256"],
        bundle_root
        / "visuals"
        / "thumbnail.webp": committed_bundle["thumbnail"]["sha256"],
        bundle_root
        / "proxies"
        / "overview.glb": committed_bundle["lodArtifacts"][0]["sha256"],
    }
    for path, digest in expected_visuals.items():
        payload = _read_bytes(path)
        assert hashlib.sha256(payload).hexdigest() == digest


def test_proposal_is_principal_and_session_bound(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    service = _service(
        repository,
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    proposal = _propose(service)
    with pytest.raises(TransactionAuthorizationError) as wrong_user:
        service.get_preview(
            proposal.proposal_id,
            _principal(principal_id="curator-b"),
            session_id="session-a",
            site_id="site-a",
        )
    assert wrong_user.value.code == "transaction_principal_mismatch"
    with pytest.raises(TransactionAuthorizationError) as wrong_session:
        service.get_preview(
            proposal.proposal_id,
            _principal(),
            session_id="session-b",
            site_id="site-a",
        )
    assert wrong_session.value.code == "transaction_principal_mismatch"


def test_unauthorized_scope_fails_without_asset_disclosure(tmp_path):
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    failures = []
    with pytest.raises(CatalogNotFoundError) as cross_tenant:
        _propose(
            service,
            principal=_principal(
                principal_id="curator-b",
                tenant_id="tenant-b",
                sites=("site-b",),
            ),
        )
    failures.append((cross_tenant.value.code, str(cross_tenant.value)))
    cross_site_bundle, _ = _render_data()
    with pytest.raises(CatalogNotFoundError) as cross_site:
        service.propose(
            _principal(sites=("site-b",)),
            session_id="session-a",
            site_id="site-a",
            intake_job_id="iaj-" + "0" * 24,
            definition=_definition(),
            render_bundle=cross_site_bundle,
            idempotency_key="publication-idem-0002",
        )
    failures.append((cross_site.value.code, str(cross_site.value)))
    assert failures == [
        ("catalog_asset_not_found", "Catalog asset was not found."),
        ("catalog_asset_not_found", "Catalog asset was not found."),
    ]


def test_only_curator_or_admin_can_propose_and_apply(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    authority = MutableAuthority(_authority())
    service = _service(repository, authority, tmp_path / "receipts")
    viewer = _principal(roles=("viewer",))
    with pytest.raises(CatalogAuthorizationError) as denied:
        _propose(service, principal=viewer)
    assert denied.value.code == "catalog_role_not_authorized"

    proposal = _propose(service)
    approval = _approve(service, proposal)
    with pytest.raises(CatalogAuthorizationError) as revoked:
        _apply(service, proposal, approval, principal=viewer)
    assert revoked.value.code == "catalog_role_not_authorized"
    assert repository.list_assets(
        _principal(roles=("viewer",)),
        site_id="site-a",
    ) == []


def test_apply_rejects_wrong_user_and_session(tmp_path):
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    proposal = _propose(service)
    approval = _approve(service, proposal)
    with pytest.raises(TransactionAuthorizationError):
        _apply(
            service,
            proposal,
            approval,
            principal=_principal(principal_id="curator-b"),
        )
    with pytest.raises(TransactionAuthorizationError):
        _apply(
            service,
            proposal,
            approval,
            session_id="session-b",
        )


def test_changed_diff_and_idempotency_key_are_rejected(tmp_path):
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    proposal = _propose(service)
    changed = ExactBinding(
        target=TransactionTarget(
            domain=proposal.binding.target.domain,
            scope_id=proposal.binding.target.scope_id,
            resource_id=proposal.binding.target.resource_id,
        ),
        base_revision=proposal.binding.base_revision,
        diff_hash="f" * 64,
        dependency_fingerprint=(
            proposal.binding.dependency_fingerprint
        ),
    )
    with pytest.raises(TransactionBindingError) as altered:
        service.approve(
            proposal.proposal_id,
            changed,
            _principal(),
            session_id="session-a",
            site_id="site-a",
            idempotency_key="publication-idem-0001",
            explicit_approval=True,
        )
    assert altered.value.code == "transaction_binding_mismatch"
    with pytest.raises(TransactionBindingError) as changed_key:
        _approve(
            service,
            proposal,
            idempotency_key="publication-idem-other",
        )
    assert changed_key.value.code == "transaction_request_mismatch"


def test_incomplete_intake_job_cannot_create_publication_proposal(tmp_path):
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    definition = _definition()
    bundle, artifacts = _render_data()
    job_id = _prepare_intake(
        service,
        definition,
        bundle,
        artifacts,
        complete=False,
    )

    with pytest.raises(CatalogValidationError) as raised:
        _propose(
            service,
            definition=definition,
            bundle=bundle,
            artifacts=artifacts,
            intake_job_id=job_id,
        )

    assert raised.value.code == "intake_candidate_not_ready"
    assert service.repository.list_assets(
        _principal(roles=("viewer",)),
        site_id="site-a",
    ) == []


def test_mismatched_completed_intake_job_cannot_create_proposal(tmp_path):
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    definition = _definition()
    bundle, artifacts = _render_data()
    job_id = _prepare_intake(
        service,
        definition,
        bundle,
        artifacts,
        candidate_render_bundle_revision="f" * 64,
    )

    with pytest.raises(CatalogValidationError) as raised:
        _propose(
            service,
            definition=definition,
            bundle=bundle,
            artifacts=artifacts,
            intake_job_id=job_id,
        )

    assert raised.value.code == "intake_candidate_mismatch"
    assert service.repository.list_assets(
        _principal(roles=("viewer",)),
        site_id="site-a",
    ) == []


@pytest.mark.parametrize("mutation", ["missing", "altered"])
def test_changed_checkpointed_artifact_bytes_fail_before_proposal(
    tmp_path,
    mutation,
):
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    definition = _definition()
    bundle, artifacts = _render_data()
    job_id = _prepare_intake(service, definition, bundle, artifacts)
    candidate = service.intake_job_store.get_publication_candidate(job_id)
    first_output = candidate["artifactInventory"][0]["relativePath"]
    source = (
        service.intake_job_store.staging_directory(job_id) / first_output
    )
    if mutation == "missing":
        source.unlink()
    else:
        source.write_bytes(b"fabricated-render-artifact")

    with pytest.raises(CatalogValidationError) as raised:
        _propose(
            service,
            definition=definition,
            bundle=bundle,
            artifacts=artifacts,
            intake_job_id=job_id,
        )

    assert raised.value.code == "intake_candidate_not_ready"
    assert service.repository.list_assets(
        _principal(roles=("viewer",)),
        site_id="site-a",
    ) == []


def test_changed_checkpointed_artifact_bytes_fail_after_approval(tmp_path):
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    proposal = _propose(service)
    approval = _approve(service, proposal)
    candidate = service.intake_job_store.get_publication_candidate(
        proposal.payload["intent"]["intakeJobId"]
    )
    first_output = candidate["artifactInventory"][0]["relativePath"]
    source = (
        service.intake_job_store.staging_directory(candidate["jobId"])
        / first_output
    )
    source.write_bytes(b"changed-after-approval")

    with pytest.raises(CatalogValidationError) as raised:
        _apply(service, proposal, approval)

    assert raised.value.code == "intake_candidate_not_ready"
    assert service.repository.list_assets(
        _principal(roles=("viewer",)),
        site_id="site-a",
    ) == []


def test_stale_registry_revision_rejects_apply_before_pointer_change(
    tmp_path,
):
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    authority = MutableAuthority(_authority())
    service = _service(repository, authority, tmp_path / "receipts")
    proposal = _propose(service)
    approval = _approve(service, proposal)

    args = authority.snapshot.registry_arguments()
    replacement_bundle, replacement_artifacts = _render_data(variant=1)
    replacement_job_id = _prepare_intake(
        service,
        _definition(),
        replacement_bundle,
        replacement_artifacts,
    )
    replacement_candidate = (
        service.intake_job_store.get_publication_candidate(
            replacement_job_id
        )
    )
    replacement_sources = (
        service.intake_job_store.resolve_checkpointed_artifacts(
            replacement_job_id,
            {
                item["sha256"]: item["byteLength"]
                for item in [
                    *replacement_bundle["lodArtifacts"],
                    replacement_bundle["thumbnail"],
                ]
            },
        )
    )
    repository.publish_asset(
        _principal(),
        site_id="site-a",
        definition=_definition(),
        render_bundle=replacement_bundle,
        artifact_sources=replacement_sources,
        intake_job_id=replacement_job_id,
        checkpoint_fingerprint=replacement_candidate[
            "checkpointFingerprint"
        ],
        as_of=NOW,
        visibility="private",
        **args,
    )
    with pytest.raises(CatalogConflictError) as stale:
        _apply(service, proposal, approval)
    assert stale.value.code == "catalog_registry_revision_conflict"
    current = repository.get_asset(
        _principal(roles=("viewer",)),
        site_id="site-a",
        asset_id="asset-machine-a",
    )
    assert current["defaultRenderBundleRevision"] != (
        proposal.public_summary["renderFingerprint"]
    )


@pytest.mark.parametrize("license_status", ["unknown", "restricted"])
def test_common_publication_rejects_unapproved_license(
    tmp_path,
    license_status,
):
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    with pytest.raises(CatalogValidationError) as blocked:
        _propose(
            service,
            definition=_definition(license_status=license_status),
            visibility="common",
        )
    assert blocked.value.code == "public_publication_not_ready"


@pytest.mark.parametrize(
    "mutation",
    ["expired", "revoked", "conflicting"],
)
def test_apply_rejects_changed_invalid_hard_evidence(
    tmp_path,
    mutation,
):
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    authority = MutableAuthority(_authority())
    service = _service(repository, authority, tmp_path / "receipts")
    proposal = _propose(service)
    approval = _approve(service, proposal)

    records = _evidence_records()
    if mutation == "expired":
        records[0]["validUntil"] = "2026-07-27T00:00:00Z"
    elif mutation == "revoked":
        records[0]["revokedAt"] = "2026-07-27T00:00:00Z"
        records[0]["revocationReason"] = "Superseded"
    else:
        records.append(
            _evidence(
                "ev-geometry-8",
                "industrial_asset.geometry.canonical",
                fingerprint="f" * 64,
            )
        )
    authority.snapshot = _authority(records=records)
    with pytest.raises(CatalogValidationError) as blocked:
        _apply(service, proposal, approval)
    assert blocked.value.code == "hard_evidence_not_authoritative"
    assert repository.list_assets(
        _principal(roles=("viewer",)),
        site_id="site-a",
    ) == []


def test_private_nonhard_conflict_remains_publishable_but_unready(tmp_path):
    records = _evidence_records()
    records.append(
        _evidence(
            "ev-loading-8",
            "industrial_asset.loading.installed",
            fingerprint="f" * 64,
        )
    )
    definition = _definition()
    definition["loading"]["evidence"].append("ev-loading-8")
    definition["evidence"].append("ev-loading-8")
    authority = MutableAuthority(_authority(records=records))
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        authority,
        tmp_path / "receipts",
    )
    proposal = _propose(service, definition=definition)
    outcome = _apply(service, proposal, _approve(service, proposal))
    assert "evidence_conflict" in outcome.receipt.payload["warnings"]
    assert (
        outcome.receipt.payload["readiness"]["planningReady"]["value"]
        is False
    )


def test_authority_snapshot_change_invalidates_exact_dependency(tmp_path):
    authority = MutableAuthority(_authority())
    service = _service(
        IndustrialAssetRegistryRepository(tmp_path / "catalog"),
        authority,
        tmp_path / "receipts",
    )
    proposal = _propose(service)
    approval = _approve(service, proposal)
    records = _evidence_records()
    records.append(
        _evidence(
            "ev-unreferenced-8",
            "industrial_asset.clearance.optional",
        )
    )
    authority.snapshot = _authority(records=records)
    with pytest.raises(TransactionBindingError) as changed:
        _apply(service, proposal, approval)
    assert changed.value.code == "transaction_binding_mismatch"


def test_registry_write_failure_keeps_pointer_unpublished_and_can_retry(
    tmp_path,
):
    class ToggleRepository(IndustrialAssetRegistryRepository):
        fail_writes = True

        def _write_registry(self, scope, registry):
            if self.fail_writes:
                raise OSError("simulated registry failure")
            return super()._write_registry(scope, registry)

    repository = ToggleRepository(tmp_path / "catalog")
    service = _service(
        repository,
        MutableAuthority(_authority()),
        tmp_path / "receipts",
    )
    proposal = _propose(service)
    approval = _approve(service, proposal)
    with pytest.raises(OSError, match="simulated registry failure"):
        _apply(service, proposal, approval)
    with pytest.raises(CatalogNotFoundError):
        repository.get_asset(
            _principal(roles=("viewer",)),
            site_id="site-a",
            asset_id="asset-machine-a",
        )
    repository.fail_writes = False
    recovered = _apply(service, proposal, approval)
    assert recovered.receipt.payload["assetId"] == "asset-machine-a"


def test_restart_recovers_commit_completed_before_receipt_finalize(
    tmp_path,
    monkeypatch,
):
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    authority = MutableAuthority(_authority())
    receipt_root = tmp_path / "receipts"
    store = JsonReceiptStore(receipt_root)
    first = _service(repository, authority, store)
    proposal = _propose(first)
    approval = _approve(first, proposal)

    def fail_finalize(_prepared, _receipt):
        raise OSError("simulated crash after catalog commit")

    monkeypatch.setattr(store, "finalize", fail_finalize)
    with pytest.raises(
        OSError,
        match="simulated crash after catalog commit",
    ):
        _apply(first, proposal, approval)
    assert repository.get_asset(
        _principal(roles=("viewer",)),
        site_id="site-a",
        asset_id="asset-machine-a",
    )["assetId"] == "asset-machine-a"

    restarted = _service(
        repository,
        authority,
        receipt_root,
        token_factory=SequentialTokens(),
    )
    recovered = restarted.apply(
        approval.approval_token,
        proposal.binding,
        _principal(),
        session_id="session-a",
        site_id="site-a",
        idempotency_key="publication-idem-0001",
    )
    assert recovered.replayed is True
    assert recovered.recovered is True
    assert recovered.receipt.payload["assetId"] == "asset-machine-a"


def test_finalized_exact_replay_after_restart_returns_canonical_receipt(
    tmp_path,
):
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    authority = MutableAuthority(_authority())
    receipt_root = tmp_path / "receipts"
    first = _service(repository, authority, receipt_root)
    proposal = _propose(first)
    approval = _approve(first, proposal)
    committed = _apply(first, proposal, approval)

    restarted = _service(repository, authority, receipt_root)
    replay = restarted.apply(
        approval.approval_token,
        proposal.binding,
        _principal(),
        session_id="session-a",
        site_id="site-a",
        idempotency_key="publication-idem-0001",
    )
    assert replay.replayed is True
    assert replay.recovered is True
    assert replay.receipt == committed.receipt


def test_render_only_publication_preserves_definition_revision(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    authority = MutableAuthority(_authority())
    service = _service(repository, authority, tmp_path / "receipts")
    first_proposal = _propose(service)
    first = _apply(
        service,
        first_proposal,
        _approve(service, first_proposal),
    )

    second_proposal = _propose(
        service,
        variant=1,
        idempotency_key="publication-idem-0002",
    )
    second = _apply(
        service,
        second_proposal,
        _approve(
            service,
            second_proposal,
            idempotency_key="publication-idem-0002",
        ),
        idempotency_key="publication-idem-0002",
    )
    assert (
        second.receipt.payload["assetDefinitionRevision"]
        == first.receipt.payload["assetDefinitionRevision"]
    )
    assert (
        second.receipt.payload["renderBundleRevision"]
        != first.receipt.payload["renderBundleRevision"]
    )
