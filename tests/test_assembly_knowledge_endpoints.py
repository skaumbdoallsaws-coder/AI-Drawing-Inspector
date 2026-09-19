from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.assembly_knowledge import (
    AssemblyKnowledgeRepository,
    adapt_bridge_package,
    authorize_enrichment_plan,
    compile_deterministic_evidence,
    execute_economy_enrichment,
    plan_enrichment_request,
    refresh_package_revision,
)
from ai_inspector.assembly_knowledge.enrichment import ENRICHMENT_PROMPT_VERSION
from ai_inspector.assembly_knowledge.provider import FixtureMultimodalProvider


PACKAGE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "packages"
    / "bridge-v1.0"
)
RESPONSE_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "assembly_knowledge"
    / "enrichment"
    / "economy_response.json"
)


def _enriched_documents(tmp_path: Path) -> dict:
    source = tmp_path / "source"
    source.mkdir(parents=True)
    root = source / "SWPR-Tricycle.SLDASM"
    root.write_bytes(b"assembly")
    (source / "Wheel.SLDPRT").write_bytes(b"wheel")
    (source / "Axle.SLDPRT").write_bytes(b"axle")
    documents = compile_deterministic_evidence(
        adapt_bridge_package(
            PACKAGE_FIXTURE,
            source_root=source,
            root_assembly=root,
            product_id="tricycle",
        ).documents
    )
    documents["package.json"]["assetHashes"] = {
        "visuals/presentation/contact-sheet.png": "1" * 64,
    }
    documents["visual_manifest.json"]["contactSheets"] = [
        {
            "contactSheetId": "sheet-1",
            "assetPath": "visuals/presentation/contact-sheet.png",
            "assetHash": "1" * 64,
            "width": 1800,
            "height": 1300,
            "viewIds": [],
        }
    ]
    plan = plan_enrichment_request(
        documents,
        provider="fixture",
        model="fixture-model-v1",
        prompt_version=ENRICHMENT_PROMPT_VERSION,
    )
    authorization = authorize_enrichment_plan(
        plan,
        explicit_approval=True,
        user_id="endpoint-user",
        session_id="endpoint-session",
        idempotency_key="endpoint-enrichment-1",
        unknown_pricing_acknowledged=True,
    )
    response = json.loads(RESPONSE_FIXTURE.read_text(encoding="ascii"))
    enriched = execute_economy_enrichment(
        documents,
        package_dir=tmp_path,
        budget_plan=plan,
        authorization=authorization,
        provider=FixtureMultimodalProvider([response]),
    )["documents"]
    asset_payload = b"fixture-review-asset"
    asset_hash = hashlib.sha256(asset_payload).hexdigest()
    enriched["package.json"]["assetHashes"] = {
        "visuals/review.bin": asset_hash,
    }
    enriched["visual_manifest.json"]["contactSheets"] = []
    return {
        "documents": refresh_package_revision(enriched),
        "assetPayload": asset_payload,
        "sourceRoot": source,
    }


@pytest.fixture
def assembly_knowledge_api(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> dict:
    training_root = tmp_path / "training"
    prepared = _enriched_documents(tmp_path / "input")
    repository = AssemblyKnowledgeRepository(training_root)
    documents = prepared["documents"]
    repository.write(
        documents,
        assets={"visuals/review.bin": prepared["assetPayload"]},
    )
    repository.bind_source_root(
        "tricycle",
        documents["package.json"]["packageId"],
        prepared["sourceRoot"],
    )
    monkeypatch.setattr(server, "PROCESS_MAP_TRAINING_ROOT", training_root)
    monkeypatch.setenv("INSPECTORPRO_PROCESS_MAP_EDIT", "1")
    monkeypatch.setenv("INSPECTORPRO_ASSEMBLY_KNOWLEDGE_REVIEW", "1")
    return {
        "root": training_root,
        "repository": repository,
        "documents": documents,
        "packageId": documents["package.json"]["packageId"],
        "assetPayload": prepared["assetPayload"],
        "sourceRoot": prepared["sourceRoot"],
    }


def test_review_routes_are_independently_flagged(
    assembly_knowledge_api: dict,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = TestClient(server.app)
    assert client.get("/api/training/assembly-knowledge-review-status").json() == {
        "success": True,
        "enabled": True,
    }
    monkeypatch.delenv("INSPECTORPRO_ASSEMBLY_KNOWLEDGE_REVIEW")
    response = client.get("/api/training/assembly-knowledge/tricycle")
    assert response.status_code == 404


def test_list_review_validate_and_asset_round_trip(
    assembly_knowledge_api: dict,
) -> None:
    client = TestClient(server.app)
    package_id = assembly_knowledge_api["packageId"]
    listing = client.get("/api/training/assembly-knowledge/tricycle")
    assert listing.status_code == 200
    package = listing.json()["packages"][0]
    assert package["packageId"] == package_id
    assert package["pendingReviewCount"] > 0

    review = client.get(
        f"/api/training/assembly-knowledge/tricycle/{package_id}/review"
    )
    assert review.status_code == 200
    payload = review.json()["review"]
    assert payload["identity"]["packageRevision"] == package["packageRevision"]
    assert payload["items"]
    assert payload["items"][0]["entities"]
    assert payload["sourceStatus"]["current"] is True

    validation = client.get(
        f"/api/training/assembly-knowledge/tricycle/{package_id}/validation"
    )
    assert validation.status_code == 200
    assert validation.json()["summary"]["valid"] is True

    asset = client.get(
        f"/api/training/assembly-knowledge/tricycle/{package_id}"
        "/assets/visuals/review.bin"
    )
    assert asset.status_code == 200
    assert asset.content == assembly_knowledge_api["assetPayload"]
    traversal = client.get(
        f"/api/training/assembly-knowledge/tricycle/{package_id}"
        "/assets/../package.json"
    )
    assert traversal.status_code in {404, 422}


def test_review_action_is_revision_bound_auditable_and_backed_up(
    assembly_knowledge_api: dict,
) -> None:
    client = TestClient(server.app)
    documents = assembly_knowledge_api["documents"]
    package = documents["package.json"]
    package_id = package["packageId"]
    review = client.get(
        f"/api/training/assembly-knowledge/tricycle/{package_id}/review"
    ).json()["review"]
    claim_id = review["items"][0]["claimId"]
    body = {
        "baseRevision": package["packageRevision"],
        "sourceRevision": package["sourceRevision"],
        "claimId": claim_id,
        "action": "confirm",
        "actor": "endpoint-reviewer",
    }
    response = client.post(
        f"/api/training/assembly-knowledge/tricycle/{package_id}/review-actions",
        json=body,
    )
    assert response.status_code == 200
    result = response.json()
    assert result["packageRevision"] != package["packageRevision"]
    loaded = assembly_knowledge_api["repository"].read("tricycle", package_id)
    event = loaded["review_receipt.json"]["events"][-1]
    assert event["action"] == "confirm"
    assert event["after"]["authority"] == "supporting"
    backup = (
        assembly_knowledge_api["repository"].package_dir("tricycle", package_id)
        / ".backups"
        / f"rev-{package['packageRevision'][:16]}"
        / "package.json"
    )
    assert backup.is_file()

    stale = client.post(
        f"/api/training/assembly-knowledge/tricycle/{package_id}/review-actions",
        json=body,
    )
    assert stale.status_code == 409
    assert stale.json()["error"] == "stale_package_revision"


def test_changed_cad_source_blocks_review_action(
    assembly_knowledge_api: dict,
) -> None:
    client = TestClient(server.app)
    documents = assembly_knowledge_api["documents"]
    package = documents["package.json"]
    package_id = package["packageId"]
    review = client.get(
        f"/api/training/assembly-knowledge/tricycle/{package_id}/review"
    ).json()["review"]
    (assembly_knowledge_api["sourceRoot"] / "Wheel.SLDPRT").write_bytes(
        b"changed-wheel"
    )
    response = client.post(
        f"/api/training/assembly-knowledge/tricycle/{package_id}/review-actions",
        json={
            "baseRevision": package["packageRevision"],
            "sourceRevision": package["sourceRevision"],
            "claimId": review["items"][0]["claimId"],
            "action": "confirm",
            "actor": "endpoint-reviewer",
        },
    )
    assert response.status_code == 409
    assert response.json()["error"] == "stale_source_revision"
