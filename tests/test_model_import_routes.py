"""Minimal FastAPI app: HTTP scope checks, streaming admission and polling contracts."""
import asyncio
import threading
from types import SimpleNamespace
from urllib.parse import quote

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.model_imports import create_model_import_router
from ai_inspector.facility_layout import model_import_store as module
from ai_inspector.industrial_assets.model_import.errors import ModelImportError
from tests.model_import_store_support import inspect_worker, layout_reader, principal, recipe, scope, store, wait

BASE = "/api/facility-layouts/a/layout"
IMPORTS = BASE + "/model-imports"


def application(tmp_path, **options):
    instance = store(tmp_path, **options)
    service = SimpleNamespace(layout_repository=SimpleNamespace(root=tmp_path), get_layout=layout_reader)
    app = FastAPI()
    def resolve(request):
        return principal(request.headers.get("x-user", "u"), request.headers.get("x-tenant", "tenant"),
                         request.headers.get("x-role", "editor"))
    app.include_router(create_model_import_router(service=service, principal_resolver=resolve, store=instance))
    return app, instance


def test_upload_returns_before_worker_finishes_then_polls_preview(tmp_path):
    entered, release = threading.Event(), threading.Event()
    def blocked(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return inspect_worker(*args, **kwargs)
    app, instance = application(tmp_path, inspect_worker=blocked)
    with TestClient(app) as client:
        response = client.post(IMPORTS, content=b"glTFfixture", headers={"X-Model-Name": quote("../../Caf\u00e9.glb")})
        assert response.status_code == 202, response.text
        record = response.json()
        assert record["state"] == "queued" and record["name"] == "Caf\u00e9.glb" and record["importId"] == record["id"]
        assert entered.wait(2)
        checking = client.get(IMPORTS + "/" + record["id"]).json()
        assert checking["state"] in ("queued", "checking")
        release.set()
        ready = wait(instance, scope(), record["id"])
        assert ready["state"] == "ready"
        picture = client.get(IMPORTS + "/" + record["id"] + "/preview", headers={"X-Role": "viewer"})
        assert picture.status_code == 200 and picture.content.startswith(b"\x89PNG")
        assert picture.headers["content-type"] == "image/png"
        assert picture.headers["x-content-type-options"] == "nosniff"
        assert picture.headers["cache-control"] == "private, no-store"
        listed = client.get(IMPORTS).json()["imports"]
        assert listed[0]["id"] == record["id"]


def test_route_permissions_and_cross_scope_missing_are_indistinguishable(tmp_path):
    app, instance = application(tmp_path)
    with TestClient(app) as client:
        assert client.post(IMPORTS, content=b"x", headers={"X-Role": "viewer"}).status_code == 403
        assert client.post(IMPORTS.replace("/layout/", "/missing/"), content=b"x").status_code == 404
        record = client.post(IMPORTS, content=b"glTFfixture").json()
        wait(instance, scope(), record["id"])
        draft = instance.prepare(scope(), recipe(record["id"]))
        for url in (IMPORTS + "/" + record["id"], IMPORTS + "/" + record["id"] + "/preview",
                    BASE + "/model-drafts/" + draft["draftId"] + "/preview"):
            own = client.get(url)
            assert own.status_code == 200
            assert client.get(url.replace("/a/", "/b/")).status_code == 404
            assert client.get(url, headers={"X-Tenant": "other"}).status_code == 404
            missing = client.get(url.replace(record["id"], "mi-" + "f" * 24).replace(
                draft["draftId"], "md-" + "f" * 24))
            foreign = client.get(url, headers={"X-Tenant": "other"})
            assert foreign.json() == missing.json()


def test_failed_retry_and_refused_records_remain_pollable(tmp_path):
    def fail(*args, **kwargs):
        raise ModelImportError("model_timeout")
    app, instance = application(tmp_path, inspect_worker=fail)
    with TestClient(app) as client:
        record = client.post(IMPORTS, content=b"glTFfixture").json()
        failed = wait(instance, scope(), record["id"])
        assert failed["state"] == "failed" and failed["refusal"]["code"] == "model_timeout"
        retry = IMPORTS + "/" + record["id"] + "/retry"
        assert client.post(retry, headers={"X-Role": "viewer"}).status_code == 403
        assert client.post(retry, headers={"X-Tenant": "other"}).status_code == 404
        instance.inspect_worker = inspect_worker
        result = client.post(retry)
        assert result.status_code == 202 and result.json()["id"] == record["id"]
        assert wait(instance, scope(), record["id"])["state"] == "ready"
        assert client.post(retry).status_code == 409
        def refuse(*args, **kwargs):
            raise ModelImportError("gltf_invalid")
        instance.inspect_worker = refuse
        refused = client.post(IMPORTS, content=b"bad").json()
        assert wait(instance, scope(), refused["id"])["state"] == "refused"
        assert client.get(IMPORTS + "/" + refused["id"]).json()["refusal"]["code"] == "gltf_invalid"


def asgi_request(app, *, headers=(), chunks=(b"x",), disconnect=False):
    """The receive counter proves admission precedes reading, unlike client-side body buffering."""
    calls, messages = [], []
    iterator = iter(chunks)
    async def receive():
        calls.append(1)
        try:
            chunk = next(iterator)
            return {"type": "http.request", "body": chunk, "more_body": True}
        except StopIteration:
            return {"type": "http.disconnect"} if disconnect else {"type": "http.request", "body": b"", "more_body": False}
    async def send(message):
        messages.append(message)
    request_scope = {"type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
                     "method": "POST", "scheme": "http", "path": IMPORTS, "raw_path": IMPORTS.encode(),
                     "query_string": b"", "headers": list(headers), "client": ("testclient", 123),
                     "server": ("test", 80), "root_path": ""}
    asyncio.run(app(request_scope, receive, send))
    return calls, messages


@pytest.mark.parametrize("reason,status", [("viewer", 403), ("busy", 429), ("quota", 507), ("size", 413)])
def test_rejections_do_not_read_the_body(tmp_path, reason, status):
    options = {"site_bytes": module.MARGIN + 10000} if reason == "quota" else {}
    app, instance = application(tmp_path, **options)
    held = []
    headers = []
    if reason == "viewer":
        headers.append((b"x-role", b"viewer"))
    if reason == "busy":
        held = [instance.begin_upload(scope(), "x", 1) for _ in range(2)]
    if reason == "size":
        headers.append((b"content-length", str(module.MAX_UPLOAD_BYTES + 1).encode()))
    calls, messages = asgi_request(app, headers=headers)
    assert calls == []
    assert next(m for m in messages if m["type"] == "http.response.start")["status"] == status
    for incoming in held:
        incoming.abort()


def test_streamed_cap_and_disconnection_release_reservations(tmp_path, monkeypatch):
    app, instance = application(tmp_path)
    monkeypatch.setattr(module, "MAX_UPLOAD_BYTES", 8)
    calls, messages = asgi_request(app, chunks=(b"1234", b"56789"))
    assert len(calls) == 2
    assert next(m for m in messages if m["type"] == "http.response.start")["status"] == 413
    assert instance._active() == []
    from starlette.requests import ClientDisconnect
    with pytest.raises(ClientDisconnect):
        asgi_request(app, chunks=(b"1234",), disconnect=True)
    assert instance._active() == []
    records = instance.list(scope())
    assert {r["state"] for r in records} == {"failed", "refused"}


def test_feature_gate_denies_writes_before_receive(tmp_path):
    instance = store(tmp_path)
    app = FastAPI()
    def denied(action):
        raise FacilityLayoutError("feature_disabled", "Disabled.", status_code=403)
    app.include_router(create_model_import_router(service=None, store=instance,
                       principal_resolver=lambda request: principal(), feature_gate=denied))
    calls, messages = asgi_request(app)
    assert calls == []
    assert next(m for m in messages if m["type"] == "http.response.start")["status"] == 403


def test_router_mount_startup_and_shutdown_do_not_create_unused_store(tmp_path):
    root = tmp_path / "unused-layouts"
    service = SimpleNamespace(layout_repository=SimpleNamespace(root=root), get_layout=layout_reader)
    app = FastAPI()
    app.include_router(create_model_import_router(service=service, principal_resolver=lambda _: principal()))
    assert not root.exists()
    with TestClient(app) as client:
        assert client.get("/unrelated-route").status_code == 404
    assert not root.exists()
