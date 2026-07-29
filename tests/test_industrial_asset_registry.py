from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path

from PIL import Image
import pytest

from ai_inspector.industrial_assets.artifacts import (
    build_aabb_proxy_glb,
    build_render_bundle_manifest,
    inspect_glb,
    normalize_web_image,
)
from ai_inspector.industrial_assets.authority import (
    EvidenceRecord,
    IndustrialAssetAuthorityError,
    TrustedSourceRegistry,
    validate_evidence_records,
)
from ai_inspector.industrial_assets.registry import (
    CatalogAuthorizationError,
    CatalogConflictError,
    CatalogNotFoundError,
    CatalogPrincipal,
    CatalogValidationError,
    CatalogIntegrityError,
    IndustrialAssetRegistryRepository,
    asset_definition_revision,
    compute_asset_readiness,
    render_bundle_revision,
)


NOW = datetime(2026, 7, 28, 12, 0, tzinfo=timezone.utc)
SOURCE_REVISION = "1" * 64
GEOMETRY_REVISION = "2" * 64


def _source_registry(
    *,
    status: str = "active",
    maximum_age_days: int = 365,
    current_revision: str = SOURCE_REVISION,
    scopes: list[str] | None = None,
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
                "permittedClaimScopes": scopes
                or [
                    "industrial_asset.geometry",
                    "industrial_asset.clearance",
                    "industrial_asset.connector",
                    "industrial_asset.loading",
                    "industrial_asset.license",
                ],
                "allowedSiteIds": ["site-a", "site-b"],
                "freshnessPolicy": {
                    "maximumAgeDays": maximum_age_days,
                },
                "currentRevision": current_revision,
            }
        ],
    }


def _evidence(
    evidence_id: str,
    claim_key: str,
    *,
    status: str = "authored",
    fingerprint: str | None = None,
    asserted_at: str = "2026-07-01T00:00:00Z",
    valid_until: str | None = None,
    revoked_at: str | None = None,
    source_revision: str = SOURCE_REVISION,
    actor: str = "authority-curator-a",
    subject_ref: dict | None = None,
    inputs: list[str] | None = None,
    method: tuple[str, str] = ("asset-normalizer", "1.0.0"),
) -> dict:
    value = {
        "schemaVersion": 1,
        "documentKind": "evidence_record",
        "evidenceId": evidence_id,
        "tenantId": "tenant-a",
        "subjectRef": subject_ref
        or {
            "documentKind": "industrial_asset_definition",
            "assetId": "asset-machine-a",
        },
        "claimKey": claim_key,
        "valueFingerprint": fingerprint or (evidence_id[-1] * 64),
        "status": status,
        "sourceRef": {
            "trustedSourceId": "source-machine-spec",
            "sourceRevision": source_revision,
            "locator": f"manufacturer/spec#{evidence_id}",
        },
        "assertedBy": actor,
        "assertedAt": asserted_at,
        "validFrom": "2026-07-01T00:00:00Z",
        "validUntil": valid_until,
        "revokedAt": revoked_at,
        "revocationReason": "Superseded" if revoked_at else None,
    }
    if status == "derived":
        value["derivation"] = {
            "methodId": method[0],
            "methodVersion": method[1],
            "inputEvidenceIds": inputs or [],
        }
    return value


def _evidence_records(*, license_status: str = "authored") -> list[dict]:
    return [
        _evidence("ev-geometry-3", "industrial_asset.geometry.canonical"),
        _evidence("ev-clearance-4", "industrial_asset.clearance.service"),
        _evidence("ev-connector-5", "industrial_asset.connector.material"),
        _evidence("ev-loading-6", "industrial_asset.loading.installed"),
        _evidence(
            "ev-license-7",
            "industrial_asset.license.redistribution",
            status=license_status,
        ),
    ]


def _definition(*, license_status: str = "verified", asset_id: str = "asset-machine-a") -> dict:
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
        "tags": ["cnc", "fixture"],
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
            "visualReady": {"value": False, "blockers": ["untrusted_input"]},
            "placementReady": {"value": False, "blockers": ["untrusted_input"]},
            "planningReady": {"value": False, "blockers": ["untrusted_input"]},
            "publicReady": {"value": False, "blockers": ["untrusted_input"]},
        },
    }


def _render_data(
    *,
    asset_id: str = "asset-machine-a",
    variant: int = 0,
) -> tuple[dict, dict[str, bytes]]:
    aabb = {
        "minimum": {"x": -1.0, "y": 0.0, "z": -1.0},
        "maximum": {
            "x": 1.0 + variant * 0.25,
            "y": 2.0,
            "z": 1.0,
        },
    }
    glb_data = build_aabb_proxy_glb(aabb)
    glb = inspect_glb(glb_data)
    image = Image.new("RGB", (48, 32), "white")
    color = (30 + variant * 20, 110, 190 - variant * 20)
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


def _bundle(
    *,
    asset_id: str = "asset-machine-a",
    variant: int = 0,
) -> dict:
    return _render_data(asset_id=asset_id, variant=variant)[0]


def _render_fixture(
    root: Path,
    *,
    asset_id: str = "asset-machine-a",
    variant: int = 0,
) -> tuple[dict, dict[str, Path]]:
    bundle, artifacts = _render_data(
        asset_id=asset_id,
        variant=variant,
    )
    artifact_root = root / "_test_render_sources" / asset_id / f"v{variant}"
    artifact_root.mkdir(parents=True, exist_ok=True)
    glb_path = artifact_root / "lod0.glb"
    thumbnail_path = artifact_root / "thumbnail.webp"
    lod_hash = str(bundle["lodArtifacts"][0]["sha256"])
    thumbnail_hash = str(bundle["thumbnail"]["sha256"])
    glb_path.write_bytes(artifacts[lod_hash])
    thumbnail_path.write_bytes(artifacts[thumbnail_hash])
    return bundle, {
        lod_hash: glb_path,
        thumbnail_hash: thumbnail_path,
    }


def _actors() -> dict[str, list[str]]:
    return {"authority-curator-a": ["authority_curator"]}


def _curator() -> CatalogPrincipal:
    return CatalogPrincipal(
        "curator-a",
        "tenant-a",
        ("site-a", "site-b"),
        ("catalog_curator",),
    )


def _viewer(
    tenant: str = "tenant-a",
    sites: tuple[str, ...] = ("site-a",),
) -> CatalogPrincipal:
    return CatalogPrincipal("viewer-a", tenant, sites, ("viewer",))


def _validated_evidence(
    records: list[dict] | None = None,
    registry: dict | None = None,
):
    return validate_evidence_records(
        registry or _source_registry(),
        records or _evidence_records(),
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles=_actors(),
        approved_derivations={
            "industrial_asset.geometry": {("asset-normalizer", "1.0.0")}
        },
        principal_roles=("catalog_curator",),
    )


def _publish(
    repository: IndustrialAssetRegistryRepository,
    *,
    principal: CatalogPrincipal | None = None,
    definition: dict | None = None,
    records: list[dict] | None = None,
    variant: int = 0,
    visibility: str = "private",
    allowed_site_ids: tuple[str, ...] = (),
    expected_registry_revision: str | None = None,
):
    selected_definition = definition or _definition()
    bundle, artifact_sources = _render_fixture(
        repository.root,
        asset_id=selected_definition["assetId"],
        variant=variant,
    )
    checkpoint_fingerprint = hashlib.sha256(
        (
            selected_definition["assetId"]
            + ":"
            + render_bundle_revision(bundle)
        ).encode("ascii")
    ).hexdigest()
    return repository.publish_asset(
        principal or _curator(),
        site_id="site-a",
        definition=selected_definition,
        render_bundle=bundle,
        artifact_sources=artifact_sources,
        intake_job_id=f"iaj-registry-{checkpoint_fingerprint[:16]}",
        checkpoint_fingerprint=checkpoint_fingerprint,
        trusted_sources=_source_registry(),
        evidence_records=records or _evidence_records(),
        asserted_actor_roles=_actors(),
        approved_derivations={},
        as_of=NOW,
        visibility=visibility,
        allowed_site_ids=allowed_site_ids,
        expected_registry_revision=expected_registry_revision,
    )


def test_trusted_source_and_evidence_records_parse_deterministically():
    registry = TrustedSourceRegistry.from_mapping(_source_registry())
    record = EvidenceRecord.from_mapping(_evidence_records()[0])
    assert registry.tenant_id == "tenant-a"
    assert registry.sources[0].trusted_source_id == "source-machine-spec"
    assert record.evidence_id == "ev-geometry-3"
    assert record.to_dict()["assertedAt"] == "2026-07-01T00:00:00Z"


def test_evidence_source_locator_is_required_by_frozen_schema():
    record = _evidence_records()[0]
    record["sourceRef"].pop("locator")
    with pytest.raises(IndustrialAssetAuthorityError) as raised:
        EvidenceRecord.from_mapping(record)
    assert raised.value.code == "invalid_evidence_locator"


def test_authored_evidence_requires_authority_curator():
    result = validate_evidence_records(
        _source_registry(),
        [_evidence_records()[0]],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles={"authority-curator-a": ["catalog_curator"]},
        principal_roles=("catalog_curator",),
    )
    state = result.states[0]
    assert state.current is False
    assert "authored_evidence_actor_not_authorized" in state.blockers


@pytest.mark.parametrize(
    ("registry_update", "record_update", "expected"),
    [
        ({"status": "revoked"}, {}, "trusted_source_revoked"),
        ({"status": "suspended"}, {}, "trusted_source_suspended"),
        ({}, {"valid_until": "2026-07-02T00:00:00Z"}, "evidence_expired"),
        ({}, {"revoked_at": "2026-07-02T00:00:00Z"}, "evidence_revoked"),
        (
            {"current_revision": "9" * 64},
            {},
            "trusted_source_revision_stale",
        ),
        (
            {"maximum_age_days": 1},
            {},
            "evidence_freshness_expired",
        ),
    ],
)
def test_expired_revoked_suspended_and_stale_evidence_fail_closed(
    registry_update,
    record_update,
    expected,
):
    registry = _source_registry(**registry_update)
    record = _evidence(
        "ev-geometry-3",
        "industrial_asset.geometry.canonical",
        **record_update,
    )
    result = validate_evidence_records(
        registry,
        [record],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles=_actors(),
        principal_roles=("catalog_curator",),
    )
    assert expected in result.states[0].blockers
    assert result.states[0].authoritative is False


def test_claim_outside_source_scope_is_not_authoritative():
    result = validate_evidence_records(
        _source_registry(scopes=["industrial_asset.geometry"]),
        [_evidence("ev-license-7", "industrial_asset.license.redistribution")],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles=_actors(),
        principal_roles=("catalog_curator",),
    )
    assert result.states[0].blockers == ("claim_scope_not_permitted",)


def test_derived_evidence_requires_pinned_approved_method_and_current_inputs():
    source = _evidence(
        "ev-input-1",
        "industrial_asset.geometry.source",
    )
    derived = _evidence(
        "ev-derived-2",
        "industrial_asset.geometry.canonical",
        status="derived",
        inputs=["ev-input-1"],
    )
    denied = validate_evidence_records(
        _source_registry(),
        [source, derived],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles=_actors(),
        approved_derivations={},
        principal_roles=("catalog_curator",),
    )
    assert "derivation_method_not_approved" in denied.state_by_id()[
        "ev-derived-2"
    ].blockers
    approved = validate_evidence_records(
        _source_registry(),
        [source, derived],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles=_actors(),
        approved_derivations={
            "industrial_asset.geometry": {
                ("asset-normalizer", "1.0.0")
            }
        },
        principal_roles=("catalog_curator",),
    )
    assert approved.state_by_id()["ev-derived-2"].authoritative is True


def test_stale_derived_input_invalidates_dependent_record():
    source = _evidence(
        "ev-input-1",
        "industrial_asset.geometry.source",
        revoked_at="2026-07-02T00:00:00Z",
    )
    derived = _evidence(
        "ev-derived-2",
        "industrial_asset.geometry.canonical",
        status="derived",
        inputs=["ev-input-1"],
    )
    result = validate_evidence_records(
        _source_registry(),
        [source, derived],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles=_actors(),
        approved_derivations={
            "industrial_asset.geometry": {
                ("asset-normalizer", "1.0.0")
            }
        },
        principal_roles=("catalog_curator",),
    )
    derived_state = result.state_by_id()["ev-derived-2"]
    assert "derived_input_stale" in derived_state.blockers
    assert derived_state.authoritative is False


def test_conflicting_current_authoritative_records_block_without_winner():
    first = _evidence(
        "ev-conflict-1",
        "industrial_asset.loading.installed",
        fingerprint="a" * 64,
    )
    second = _evidence(
        "ev-conflict-2",
        "industrial_asset.loading.installed",
        fingerprint="b" * 64,
    )
    result = validate_evidence_records(
        _source_registry(),
        [second, first],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles=_actors(),
        principal_roles=("catalog_curator",),
    )
    assert all(not item.authoritative for item in result.states)
    finding = next(
        item for item in result.findings if item.code == "evidence_conflict"
    )
    assert finding.evidence_ids == ("ev-conflict-1", "ev-conflict-2")
    repeated = validate_evidence_records(
        _source_registry(),
        [first, second],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles=_actors(),
        principal_roles=("catalog_curator",),
    )
    assert finding.finding_id == next(
        item
        for item in repeated.findings
        if item.code == "evidence_conflict"
    ).finding_id


def test_inferred_evidence_remains_current_but_never_authoritative():
    record = _evidence(
        "ev-inferred-9",
        "industrial_asset.clearance.service",
        status="inferred",
        actor="sage",
    )
    result = validate_evidence_records(
        _source_registry(),
        [record],
        tenant_id="tenant-a",
        site_id="site-a",
        as_of=NOW,
        asserted_actor_roles={},
        principal_roles=("catalog_curator",),
    )
    assert result.states[0].current is True
    assert result.states[0].authoritative is False
    assert result.states[0].status == "inferred"


def test_complete_reviewed_asset_is_ready_across_all_four_gates():
    readiness = compute_asset_readiness(
        _definition(),
        _bundle(),
        _validated_evidence(),
    )
    assert readiness.to_dict() == {
        "visualReady": {"value": True, "blockers": []},
        "placementReady": {"value": True, "blockers": []},
        "planningReady": {"value": True, "blockers": []},
        "publicReady": {"value": True, "blockers": []},
    }


def test_readiness_is_computed_not_trusted_from_definition_flags():
    definition = _definition()
    definition["coordinateFrame"]["alignmentResidualMeters"] = 0.2
    definition["readiness"] = {
        key: {"value": True, "blockers": []}
        for key in (
            "visualReady",
            "placementReady",
            "planningReady",
            "publicReady",
        )
    }
    bundle = _bundle()
    bundle["thumbnail"]["nonblank"] = False
    readiness = compute_asset_readiness(
        definition,
        bundle,
        _validated_evidence(),
    )
    assert readiness.visual_ready.value is False
    assert readiness.placement_ready.value is False
    assert readiness.planning_ready.value is False


def test_unknown_license_blocks_public_but_not_private_catalog_use(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    publication = _publish(
        repository,
        definition=_definition(license_status="unknown"),
    )
    assert publication.entry.readiness.public_ready.value is False
    visible = repository.get_asset(
        _viewer(),
        site_id="site-a",
        asset_id="asset-machine-a",
    )
    assert visible["safeProvenance"]["licenseStatus"] == "unknown"
    assert visible["readiness"]["publicReady"]["value"] is False


@pytest.mark.parametrize("license_status", ["unknown", "restricted", "review_required"])
def test_common_publication_fails_when_license_is_not_verified(
    tmp_path,
    license_status,
):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    with pytest.raises(CatalogValidationError) as raised:
        _publish(
            repository,
            definition=_definition(license_status=license_status),
            visibility="common",
        )
    assert raised.value.code == "public_publication_not_ready"
    assert not (tmp_path / "_common" / "registry.json").exists()


def test_common_public_ready_asset_is_visible_cross_tenant(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    publication = _publish(repository, visibility="common")
    assert publication.entry.readiness.public_ready.value is True
    visible = repository.get_asset(
        _viewer("tenant-b", ("site-b",)),
        site_id="site-b",
        asset_id="asset-machine-a",
    )
    assert visible["assetId"] == "asset-machine-a"
    assert visible["safeProvenance"]["licenseStatus"] == "verified"


def test_only_catalog_curator_or_admin_can_publish(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    editor = CatalogPrincipal(
        "editor-a",
        "tenant-a",
        ("site-a",),
        ("editor",),
    )
    with pytest.raises(CatalogAuthorizationError) as raised:
        _publish(repository, principal=editor)
    assert raised.value.code == "catalog_role_not_authorized"


def test_cross_tenant_and_cross_site_reads_match_missing_asset_response(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    _publish(repository)
    failures = []
    cases = [
        (
            _viewer("tenant-b", ("site-b",)),
            {"site_id": "site-b", "scope": "tenant-a"},
        ),
        (
            _viewer("tenant-a", ("site-b",)),
            {"site_id": "site-a", "scope": "tenant-a"},
        ),
        (
            _viewer(),
            {"site_id": "site-a", "scope": "tenant-a", "asset_id": "missing"},
        ),
    ]
    for principal, options in cases:
        asset_id = options.pop("asset_id", "asset-machine-a")
        with pytest.raises(CatalogNotFoundError) as raised:
            repository.get_asset(
                principal,
                asset_id=asset_id,
                **options,
            )
        failures.append((raised.value.code, str(raised.value)))
    assert len(set(failures)) == 1


def test_site_shared_visibility_obeys_explicit_site_grant(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    _publish(
        repository,
        visibility="site_shared",
        allowed_site_ids=("site-a",),
    )
    assert repository.get_asset(
        _viewer("tenant-a", ("site-a",)),
        site_id="site-a",
        asset_id="asset-machine-a",
    )["assetId"] == "asset-machine-a"
    with pytest.raises(CatalogNotFoundError):
        repository.get_asset(
            _viewer("tenant-a", ("site-b",)),
            site_id="site-b",
            asset_id="asset-machine-a",
        )


@pytest.mark.parametrize("visibility", ["private", "tenant_shared"])
def test_owner_tenant_can_read_private_and_tenant_shared_at_permitted_site(
    tmp_path,
    visibility,
):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    _publish(repository, visibility=visibility)
    result = repository.get_asset(
        _viewer("tenant-a", ("site-b",)),
        site_id="site-b",
        asset_id="asset-machine-a",
    )
    assert result["assetId"] == "asset-machine-a"


def test_catalog_projection_never_exposes_protected_provenance(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    _publish(repository)
    projection = repository.get_asset(
        _viewer(),
        site_id="site-a",
        asset_id="asset-machine-a",
    )
    serialized = json.dumps(projection)
    for field in (
        "sourcePath",
        "localPath",
        "storageKey",
        "licenseDocumentPath",
        "rawLicenseDocument",
        "internalNotes",
    ):
        assert field not in serialized


def test_tampered_registry_protected_provenance_fails_closed(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    _publish(repository)
    path = tmp_path / "tenant-a" / "registry.json"
    registry = json.loads(path.read_text(encoding="ascii"))
    registry["entries"][0]["safeProvenance"]["sourcePath"] = "secret"
    path.write_text(
        json.dumps(registry, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n",
        encoding="ascii",
    )
    with pytest.raises(CatalogIntegrityError) as raised:
        repository.get_asset(
            _viewer(),
            site_id="site-a",
            asset_id="asset-machine-a",
        )
    assert raised.value.code == "catalog_registry_invalid"


@pytest.mark.parametrize("field", ["sourcePath", "licenseDocumentPath", "internalNotes"])
def test_protected_provenance_is_rejected_before_write(tmp_path, field):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    definition = _definition()
    definition["provenance"][field] = "secret"
    with pytest.raises(CatalogValidationError) as raised:
        _publish(repository, definition=definition)
    assert raised.value.code == "protected_provenance_field"
    assert not (tmp_path / "tenant-a" / "registry.json").exists()


def test_registry_is_canonical_sorted_and_authoritative(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    first = _publish(repository)
    definition = _definition(asset_id="asset-machine-b")
    second_records = deepcopy(_evidence_records())
    for item in second_records:
        item["subjectRef"]["assetId"] = "asset-machine-b"
    _publish(
        repository,
        definition=definition,
        records=second_records,
        expected_registry_revision=first.registry_revision,
    )
    path = tmp_path / "tenant-a" / "registry.json"
    payload = path.read_bytes()
    assert payload.endswith(b"\n")
    assert all(byte < 128 for byte in payload)
    registry = json.loads(payload.decode("ascii"))
    assert [item["assetId"] for item in registry["entries"]] == [
        "asset-machine-a",
        "asset-machine-b",
    ]


def test_registry_cas_fails_before_changing_authoritative_pointer(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    stale = repository.registry_revision("tenant-a")
    first = _publish(
        repository,
        expected_registry_revision=stale,
    )
    with pytest.raises(CatalogConflictError) as raised:
        _publish(
            repository,
            variant=1,
            expected_registry_revision=stale,
        )
    assert raised.value.code == "catalog_registry_revision_conflict"
    current = repository.get_asset(
        _viewer(),
        site_id="site-a",
        asset_id="asset-machine-a",
    )
    assert (
        current["defaultRenderBundleRevision"]
        == first.render_bundle_revision
    )


def test_render_only_update_preserves_definition_revision(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    first = _publish(repository)
    second = _publish(
        repository,
        variant=1,
        expected_registry_revision=first.registry_revision,
    )
    assert (
        second.asset_definition_revision
        == first.asset_definition_revision
    )
    assert second.render_bundle_revision != first.render_bundle_revision
    assert asset_definition_revision(_definition()) == first.asset_definition_revision
    assert render_bundle_revision(_bundle()) == first.render_bundle_revision


@pytest.mark.parametrize("mutation", ["missing", "altered"])
def test_registry_rejects_missing_or_altered_render_artifact_bytes(
    tmp_path,
    mutation,
):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    definition = _definition()
    bundle, artifact_sources = _render_fixture(
        repository.root,
        asset_id=definition["assetId"],
    )
    lod_hash = str(bundle["lodArtifacts"][0]["sha256"])
    if mutation == "missing":
        artifact_sources.pop(lod_hash)
    else:
        artifact_sources[lod_hash].write_bytes(
            build_aabb_proxy_glb(
                {
                    "minimum": {"x": -2.0, "y": 0.0, "z": -1.0},
                    "maximum": {"x": 2.0, "y": 2.0, "z": 1.0},
                }
            )
        )
    checkpoint_fingerprint = hashlib.sha256(
        b"adversarial-registry-checkpoint"
    ).hexdigest()

    with pytest.raises(CatalogValidationError) as raised:
        repository.publish_asset(
            _curator(),
            site_id="site-a",
            definition=definition,
            render_bundle=bundle,
            artifact_sources=artifact_sources,
            intake_job_id="iaj-registry-adversarial",
            checkpoint_fingerprint=checkpoint_fingerprint,
            trusted_sources=_source_registry(),
            evidence_records=_evidence_records(),
            asserted_actor_roles=_actors(),
            approved_derivations={},
            as_of=NOW,
        )

    assert raised.value.code == {
        "missing": "staged_artifact_missing",
        "altered": "glb_sha256_mismatch",
    }[mutation]
    assert not (tmp_path / "tenant-a" / "registry.json").exists()


def test_catalog_visual_files_exist_and_hash_match_after_commit(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    publication = _publish(repository)
    bundle = _bundle()
    bundle_root = (
        tmp_path
        / "tenant-a"
        / "assets"
        / "asset-machine-a"
        / "render_bundles"
        / publication.render_bundle_revision
    )
    expected = {
        bundle_root / "visuals" / "lod0.glb": bundle["lodArtifacts"][0][
            "sha256"
        ],
        bundle_root
        / "visuals"
        / "thumbnail.webp": bundle["thumbnail"]["sha256"],
        bundle_root
        / "proxies"
        / "overview.glb": bundle["lodArtifacts"][0]["sha256"],
    }
    for path, digest in expected.items():
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == digest
    stored_manifest = json.loads(
        (bundle_root / "manifest.json").read_text(encoding="ascii")
    )
    assert stored_manifest == bundle
    assert publication.entry.intake_job_id is not None
    assert publication.entry.checkpoint_fingerprint is not None


def test_registry_write_failure_never_publishes_partial_artifacts(tmp_path):
    class FailingRegistryRepository(IndustrialAssetRegistryRepository):
        def _write_registry(self, scope, registry):
            raise OSError("simulated registry failure")

    repository = FailingRegistryRepository(tmp_path)
    with pytest.raises(OSError, match="simulated"):
        _publish(repository)
    assert (
        list(
            (tmp_path / "tenant-a" / "assets").glob(
                "asset-machine-a/definitions/*/asset.json"
            )
        )
    )
    with pytest.raises(CatalogNotFoundError):
        repository.get_asset(
            _viewer(),
            site_id="site-a",
            asset_id="asset-machine-a",
        )


def test_directory_drift_is_not_treated_as_publication(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    drift = (
        tmp_path
        / "tenant-a"
        / "assets"
        / "asset-drift"
        / "definitions"
        / ("d" * 64)
    )
    drift.mkdir(parents=True)
    (drift / "asset.json").write_text("{}", encoding="ascii")
    assert repository.list_assets(_viewer(), site_id="site-a") == []
    with pytest.raises(CatalogNotFoundError):
        repository.get_asset(
            _viewer(),
            site_id="site-a",
            asset_id="asset-drift",
        )


def test_tampered_definition_revision_is_rejected_on_read(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    publication = _publish(repository)
    path = (
        tmp_path
        / "tenant-a"
        / "assets"
        / "asset-machine-a"
        / "definitions"
        / publication.asset_definition_revision
        / "asset.json"
    )
    definition = json.loads(path.read_text(encoding="ascii"))
    definition["displayName"] = "Tampered"
    path.write_text(
        json.dumps(
            definition,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n",
        encoding="ascii",
    )
    with pytest.raises(CatalogIntegrityError) as raised:
        repository.get_asset_definition(
            _viewer(),
            site_id="site-a",
            asset_id="asset-machine-a",
        )
    assert raised.value.code == "catalog_definition_revision_mismatch"


def test_invalid_evidence_reference_blocks_publication(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    definition = _definition()
    definition["evidence"].append("ev-missing-8")
    with pytest.raises(CatalogValidationError) as raised:
        _publish(repository, definition=definition)
    assert raised.value.code == "referenced_evidence_missing"


def test_common_publication_is_blocked_by_conflicting_license_evidence(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    records = _evidence_records()
    records.append(
        _evidence(
            "ev-license-8",
            "industrial_asset.license.redistribution",
            fingerprint="f" * 64,
        )
    )
    definition = _definition()
    definition["provenance"]["evidence"].append("ev-license-8")
    definition["evidence"].append("ev-license-8")
    with pytest.raises(CatalogValidationError) as raised:
        _publish(
            repository,
            definition=definition,
            records=records,
            visibility="common",
        )
    assert raised.value.code == "public_publication_not_ready"


def test_private_asset_with_conflicting_evidence_remains_visible_as_unready(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
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
    publication = _publish(
        repository,
        definition=definition,
        records=records,
        visibility="private",
    )
    assert publication.entry.readiness.planning_ready.value is False
    assert any(
        item["code"] == "evidence_conflict"
        for item in publication.entry.authority_findings
    )


def test_asset_definition_read_projection_uses_registry_effective_readiness(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    _publish(repository)
    result = repository.get_asset_definition(
        _viewer(),
        site_id="site-a",
        asset_id="asset-machine-a",
    )
    assert result["readiness"]["visualReady"]["value"] is True
    assert result["definition"]["readiness"]["visualReady"]["value"] is False
    assert (
        result["assetDefinitionRevision"]
        == asset_definition_revision(result["definition"])
    )


def test_invalid_authority_record_fails_before_catalog_write(tmp_path):
    repository = IndustrialAssetRegistryRepository(tmp_path)
    records = _evidence_records()
    records[0]["valueFingerprint"] = "not-a-revision"
    with pytest.raises(IndustrialAssetAuthorityError):
        _publish(repository, records=records)
    assert not (tmp_path / "tenant-a" / "registry.json").exists()
