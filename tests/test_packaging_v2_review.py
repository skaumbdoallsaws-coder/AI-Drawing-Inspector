"""Offline review regressions: real router, admission, gateway and SQLite service."""
import asyncio
from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ai_inspector.codex_runtime.packaging_tools import PackagingGateway, packaging_scope
from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.admission import PackagingAdmission
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.models import Design
from ai_inspector.packaging_shipping.service import PackagingService


HEADERS = {"X-InspectorPro-Request": "packaging"}


class OfflineRating:
    def status(self):
        return {"configured": False, "purchases_enabled": False}

    async def quote(self, *args, **kwargs):
        raise AssertionError("Review regressions must never contact a carrier")


@pytest.fixture
def host(tmp_path):
    principal = FacilityPrincipal(principal_id="review-user", tenant_id="review-tenant",
                                  allowed_site_ids=("review-site",), roles=("editor",))
    service = PackagingService(tmp_path / "store")
    registry = PackagingAdmission(service, ttl_seconds=300)
    scope = packaging_scope(principal)
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal,
        static_root=Path(__file__).resolve().parents[1] / "static", admission=registry,
        rating=OfflineRating()))
    with TestClient(app, headers=HEADERS, raise_server_exceptions=False) as client:
        yield SimpleNamespace(service=service, registry=registry, scope=scope,
                              principal=principal, client=client)


@pytest.mark.parametrize("operation", ["publish", "heartbeat", "revoke", "deep_json", "oversize_json", "broken_json"])
def test_invalid_editor_transition_revokes_old_write_authority(host, operation):
    original = host.service.create(host.scope, Design(name="Original selected document"))
    other = host.service.create(host.scope, Design(name="New selected document"))
    state = {"document_id": original["id"], "revision": 0, "session_id": "review-session",
             "conversation_id": "review-conversation", "active_mode": "packaging_shipping",
             "dirty": False, "conflict": False, "pending_operations": 0}
    published = host.client.post("/api/packaging/editor", json=state)
    assert published.status_code == 200, published.text
    admitted = published.json()
    turn = host.registry.begin(host.principal, admitted["admission_id"],
        session_id=state["session_id"], conversation_id=state["conversation_id"], turn_id="review-turn",
        direct_edit_authorized=True, principal_resolver=lambda: host.principal)
    try:
        gateway = PackagingGateway(host.service, current_context=turn.current_context,
                                   mutation_guard=turn.mutation_guard, turn_id="review-turn")
        if operation in ("publish", "deep_json", "oversize_json", "broken_json"):
            path = "/api/packaging/editor"
            body = {**state, "document_id": other["id"], "revision": "0"}
        elif operation == "heartbeat":
            path = f"/api/packaging/editor/{admitted['admission_id']}/heartbeat"
            body = {**state, "selection_id": admitted["selection_id"], "dirty": "true"}
        else:
            path = f"/api/packaging/editor/{admitted['admission_id']}/revoke"
            body = {"selection_id": ""}
        if operation == "deep_json":
            rejected = host.client.post(path, content=b"["*30000+b"0"+b"]"*30000, headers={"Content-Type": "application/json"})
        elif operation == "oversize_json":
            rejected = host.client.post(path, content=b" "*65537, headers={"Content-Type": "application/json"})
        elif operation == "broken_json":
            rejected = host.client.post(path, content=b'{"broken', headers={"Content-Type": "application/json"})
        else:
            rejected = host.client.post(path, json=body)
        assert rejected.status_code in (400, 409, 422), rejected.text

        result = asyncio.run(gateway.call("edit_packaging", {
            "expected_revision": 0, "request_id": "after-rejected-transition",
            "design": Design(name="Must not overwrite old selection").model_dump(mode="json"),
        }))
        saved = host.service.get(host.scope, original["id"])
        assert not result["ok"], (
            f"Rejected {operation} left the old admission live; gateway committed "
            f"revision {saved['revision']}: {result}"
        )
        assert saved["revision"] == 0
        assert saved["design"] == original["design"]
        assert host.service.get(host.scope, other["id"]) == other
        assert turn.cancel_event.is_set()
    finally:
        turn.close()


@pytest.mark.parametrize("content_type", ["application/json", "application/vnd.packaging+json", None])
def test_document_json_limit_covers_every_json_media_type(host, content_type):
    # Whitespace keeps the parsed model tiny; only transport/body size is excessive.
    payload = b'{"name":"TEST bounded document"}' + b" " * (1024 * 1024)
    headers = {"Content-Type": content_type} if content_type is not None else {}
    response = host.client.post("/api/packaging/documents", content=payload, headers=headers)
    documents = host.service.list(host.scope)
    assert response.status_code == 413, (
        f"Oversized JSON with Content-Type {content_type!r} returned {response.status_code}; "
        f"created {len(documents)} document(s)"
    )
    assert response.json()["error"]["code"] == "upload_too_large"
    assert documents == []


@pytest.mark.parametrize("density", [1000.0, 1000.001, 1190.0])
def test_step_mass_above_product_limit_is_a_client_error_not_server_failure(host, density):
    # A one-cubic-metre closed solid is inside STEP's supported dimension/volume caps.
    metadata = {"name": "TEST metre cube", "format": "step", "dimensions_m": [1.0, 1.0, 1.0],
                "source_revision": "a" * 64, "volume_m3": 1.0,
                "physical_evidence": {"volume_basis": "closed_solid_brep"}}
    source = host.service.store_source(host.scope, metadata, b"TEST immutable geometry")
    before = host.service.source(host.scope, source["id"])
    response = host.client.post(f"/api/packaging/sources/{source['id']}/mass-estimate", json={
        "source_revision": source["source_revision"],
        "material": {"name": "TEST material", "density_kg_m3": density,
                     "evidence": "TEST documented density"},
    })
    assert host.service.source(host.scope, source["id"]) == before
    assert host.service.list(host.scope) == []
    if density <= 1000.0:
        assert response.status_code == 200, response.text
        assert response.json()["product"]["mass_kg"] == density
    else:
        assert 400 <= response.status_code < 500, (
            f"Valid source/density yielding {density} kg returned {response.status_code}: {response.text}"
        )
        assert response.json()["error"]["code"]


def test_create_retry_is_durable_scoped_and_content_bound(host):
    from ai_inspector.packaging_shipping.models import Edit
    from ai_inspector.packaging_shipping.service import PackagingError

    design = Design(name="TEST idempotent first save")
    headers = {"Idempotency-Key": "create-review-1"}
    first = host.client.post("/api/packaging/documents", json=design.model_dump(mode="json"), headers=headers)
    assert first.status_code == 200
    original = first.json()
    assert host.client.post("/api/packaging/documents", json=design.model_dump(mode="json"), headers=headers).json() == original
    reopened = PackagingService(host.service.root)
    assert reopened.create(host.scope, design, request_id="create-review-1") == original
    reopened.change(host.scope, original["id"], Edit(expected_revision=0, request_id="review-edit",
                                                   design=Design(name="TEST later edit")))
    assert reopened.create(host.scope, design, request_id="create-review-1") == original
    assert reopened.get(host.scope, original["id"])["revision"] == 1
    with pytest.raises(PackagingError, match="different content"):
        reopened.create(host.scope, Design(name="Wrong retry"), request_id="create-review-1")
    assert len(reopened.list(host.scope)) == 1
    assert reopened.create("other-scope", design, request_id="create-review-1")["id"] != original["id"]


@pytest.mark.parametrize("key", ["", "bad key", "a" * 81, "../bad"])
def test_invalid_create_id_is_rejected_without_a_document(host, key):
    response = host.client.post("/api/packaging/documents", json={"name": "TEST rejected creation"},
                                headers={"Idempotency-Key": key})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_id_invalid"
    assert host.service.list(host.scope) == []


def test_concurrent_create_retry_commits_one_document(host):
    from concurrent.futures import ThreadPoolExecutor

    design = Design(name="TEST concurrent save retry")
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(host.service.create, host.scope, design, request_id="create-concurrent") for _ in range(8)]
        results = [future.result() for future in futures]
    assert all(result == results[0] for result in results)
    assert len(host.service.list(host.scope)) == 1
