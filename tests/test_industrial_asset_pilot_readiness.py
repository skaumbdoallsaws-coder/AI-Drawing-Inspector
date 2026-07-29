from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import hashlib

import pytest

from ai_inspector.industrial_assets.artifacts import (
    build_render_bundle_manifest,
    inspect_glb,
    normalize_web_image,
)
from ai_inspector.industrial_assets.authority import (
    TrustedSourceRegistry,
    validate_evidence_records,
)
from ai_inspector.industrial_assets.registry import (
    CatalogPrincipal,
    IndustrialAssetRegistryRepository,
    render_bundle_revision,
)


ROOT = Path(__file__).resolve().parents[1]
GENERATED_ROOT = ROOT / "generated" / "industrial_assets" / "p0_spike"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "facility_layout" / "assets"
PILOT_PATH = FIXTURE_ROOT / "p2-pilot-asset-readiness.json"
TENANT_ID = "tenant-p0-spike"
SITE_ID = "site-p0"
SOURCE_REVISION = "7" * 64


def _pilot() -> dict:
    return json.loads(PILOT_PATH.read_text(encoding="ascii"))


def _real_assets_or_skip(pilot: dict) -> None:
    missing = []
    for asset in pilot["assets"]:
        folder = GENERATED_ROOT / asset["folder"]
        for field in ("detail", "overview", "thumbnail"):
            path = folder / asset[field]["artifactName"]
            if not path.exists():
                missing.append(str(path))
        source_thumbnail = folder / asset["sourceThumbnail"]
        if not source_thumbnail.exists():
            missing.append(str(source_thumbnail))
    if missing:
        pytest.skip("P2 local pilot artifacts are unavailable")


def _authority_for(definition: dict):
    source = TrustedSourceRegistry.from_mapping(
        {
            "schemaVersion": 1,
            "documentKind": "trusted_source_registry",
            "tenantId": TENANT_ID,
            "sources": [
                {
                    "trustedSourceId": "source-p0-review",
                    "ownerTenantId": TENANT_ID,
                    "sourceType": "site_record",
                    "issuer": "InspectorPro P0 engineering review",
                    "status": "active",
                    "permittedClaimScopes": ["industrial_asset"],
                    "allowedSiteIds": [SITE_ID],
                    "freshnessPolicy": {"maximumAgeDays": 3650},
                    "currentRevision": SOURCE_REVISION,
                }
            ],
        }
    )
    records = []
    for evidence_id in definition["evidence"]:
        if evidence_id.endswith("-license"):
            claim_key = "industrial_asset.license.redistribution"
        elif evidence_id.endswith("-provider"):
            claim_key = "industrial_asset.provenance"
        elif evidence_id.endswith("-source-hash"):
            claim_key = "industrial_asset.source.hash"
        elif evidence_id.endswith("-view-review"):
            claim_key = "industrial_asset.geometry.canonical.review"
        else:
            claim_key = "industrial_asset.geometry.extraction"
        records.append(
            {
                "schemaVersion": 1,
                "documentKind": "evidence_record",
                "evidenceId": evidence_id,
                "tenantId": TENANT_ID,
                "subjectRef": {
                    "documentKind": "industrial_asset_definition",
                    "assetId": definition["assetId"],
                },
                "claimKey": claim_key,
                "valueFingerprint": hashlib.sha256(
                    f"{definition['assetId']}:{evidence_id}".encode("ascii")
                ).hexdigest(),
                "status": "authored",
                "sourceRef": {
                    "trustedSourceId": "source-p0-review",
                    "sourceRevision": SOURCE_REVISION,
                    "locator": f"p0-review/{definition['assetId']}#{evidence_id}",
                },
                "assertedBy": "authority-curator-p0",
                "assertedAt": "2026-07-28T00:00:00Z",
                "validFrom": "2026-07-28T00:00:00Z",
                "validUntil": None,
                "revokedAt": None,
                "revocationReason": None,
            }
        )
    result = validate_evidence_records(
        source,
        records,
        tenant_id=TENANT_ID,
        site_id=SITE_ID,
        as_of=datetime(2026, 7, 29, tzinfo=timezone.utc),
        asserted_actor_roles={
            "authority-curator-p0": ["authority_curator"],
        },
        approved_derivations={},
        principal_roles=("catalog_curator",),
    )
    return source, records, result


def test_p2_pilot_readiness_record_is_safe_complete_and_deterministic():
    pilot = _pilot()
    assert pilot["schemaVersion"] == "industrial-asset-p2-pilot-readiness-v1"
    assert re.fullmatch(r"[0-9a-f]{64}", pilot["geometryInterfaceRevision"])
    assets = pilot["assets"]
    assert [item["assetId"] for item in assets] == sorted(
        item["assetId"] for item in assets
    )
    assert {item["category"] for item in assets} == {
        "cnc_machine",
        "forklift",
        "rack",
        "workstation",
    }
    assert sum(
        item["expectedReadiness"]["placementReady"] for item in assets
    ) == 2
    assert all(item["expectedReadiness"]["visualReady"] for item in assets)
    assert not any(item["expectedReadiness"]["publicReady"] for item in assets)
    serialized = json.dumps(pilot, ensure_ascii=True, sort_keys=True)
    assert "C:\\" not in serialized
    assert "OneDrive" not in serialized
    for asset in assets:
        for field in ("detail", "overview", "thumbnail"):
            record = asset[field]
            assert record["byteLength"] > 0
            assert re.fullmatch(r"[0-9a-f]{64}", record["sha256"])
        assert re.fullmatch(r"[0-9a-f]{64}", asset["renderBundleRevision"])


def test_real_p2_pilot_visual_artifacts_match_exact_bundle_revisions():
    pilot = _pilot()
    _real_assets_or_skip(pilot)
    geometry_revision = pilot["geometryInterfaceRevision"]
    for asset in pilot["assets"]:
        folder = GENERATED_ROOT / asset["folder"]
        detail = inspect_glb(
            folder / asset["detail"]["artifactName"],
            expected_sha256=asset["detail"]["sha256"],
            expected_byte_length=asset["detail"]["byteLength"],
        )
        overview = inspect_glb(
            folder / asset["overview"]["artifactName"],
            expected_sha256=asset["overview"]["sha256"],
            expected_byte_length=asset["overview"]["byteLength"],
        )
        normalized_thumbnail = normalize_web_image(
            folder / asset["sourceThumbnail"],
            output_format="WEBP",
        )
        assert normalized_thumbnail.manifest["sha256"] == asset["thumbnail"]["sha256"]
        assert len(normalized_thumbnail.data) == asset["thumbnail"]["byteLength"]
        lods = {"lod0": detail}
        overview_lod = "lod0"
        if overview.sha256 != detail.sha256:
            lods["lod1"] = overview
            overview_lod = "lod1"
        bundle = build_render_bundle_manifest(
            asset_id=asset["assetId"],
            geometry_interface_revision=geometry_revision,
            lods=lods,
            overview_lod=overview_lod,
            thumbnail=normalized_thumbnail,
            expected_aabb=detail.aabb,
        )
        assert bundle.render_bundle_revision == asset["renderBundleRevision"]
        assert bundle.manifest["validation"]["nonblankThumbnail"] is True
        assert bundle.manifest["validation"]["boundsConsistent"] is True
        assert bundle.manifest["validation"]["budgets"]["withinBudget"] is True


def test_reviewed_machine_and_workstation_publish_private_as_placement_ready(
    tmp_path,
):
    pilot = _pilot()
    _real_assets_or_skip(pilot)
    repository = IndustrialAssetRegistryRepository(tmp_path / "catalog")
    principal = CatalogPrincipal(
        principal_id="catalog-curator-p0",
        tenant_id=TENANT_ID,
        site_ids=(SITE_ID,),
        roles=("catalog_curator",),
    )
    placement_ready = []
    for asset in pilot["assets"]:
        fixture_name = asset["definitionFixture"]
        if fixture_name is None:
            continue
        definition = json.loads(
            (FIXTURE_ROOT / fixture_name).read_text(encoding="ascii")
        )
        source, records, _ = _authority_for(definition)
        bundle = json.loads(
            (
                GENERATED_ROOT
                / asset["folder"]
                / "render_bundle_manifest.json"
            ).read_text(encoding="ascii")
        )
        assert render_bundle_revision(bundle) == asset["renderBundleRevision"]
        folder = GENERATED_ROOT / asset["folder"]
        artifact_sources = {
            asset["detail"]["sha256"]: (
                folder / asset["detail"]["artifactName"]
            ),
            asset["overview"]["sha256"]: (
                folder / asset["overview"]["artifactName"]
            ),
            asset["thumbnail"]["sha256"]: folder / "thumbnail.webp",
        }
        publication = repository.publish_asset(
            principal,
            site_id=SITE_ID,
            definition=definition,
            render_bundle=bundle,
            artifact_sources=artifact_sources,
            intake_job_id=(
                "iaj-pilot-"
                + hashlib.sha256(
                    asset["assetId"].encode("ascii")
                ).hexdigest()[:24]
            ),
            checkpoint_fingerprint=hashlib.sha256(
                (
                    asset["assetId"]
                    + asset["renderBundleRevision"]
                ).encode("ascii")
            ).hexdigest(),
            trusted_sources=source,
            evidence_records=records,
            asserted_actor_roles={
                "authority-curator-p0": ["authority_curator"],
            },
            approved_derivations={},
            as_of=datetime(2026, 7, 29, tzinfo=timezone.utc),
            visibility="private",
        )
        readiness = publication.entry.readiness
        assert readiness.visual_ready.value is True
        assert readiness.placement_ready.value is True
        assert readiness.public_ready.value is False
        placement_ready.append(publication.entry.asset_id)
    assert placement_ready == [
        "asset-cnc-vmc-f26678cafa91",
        "asset-wa01-e773742615b2",
    ]
