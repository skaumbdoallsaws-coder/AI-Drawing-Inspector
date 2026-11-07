"""Storage limits and the user-confirmed Remove unused (P5 retention). Offline: throwaway stores, TEST data only.

Nothing is deleted automatically, a full workspace refuses new imports, and Remove unused deletes only models and
images that no stored record names, after the exact list is confirmed."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
from pathlib import Path
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.admission import packaging_scope
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.models import StorageLimits
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from ai_inspector.packaging_shipping.storage import DEFAULT_LIMITS, MIB

HEADERS = {"X-InspectorPro-Request": "packaging"}
SCOPE = packaging_scope(FacilityPrincipal("engineer", "tenant-a", ("site-a",), ("editor",)))  # The scope the routes use.


def source(service, name, size=1024, scope=SCOPE):
    revision = sha256(name.encode()).hexdigest()
    return service.store_source(scope, {"name": name, "dimensions_m": [0.1, 0.06, 0.04], "source_revision": revision,
                                        "mass_basis": "unknown", "mass_kg": None}, b"G" * size)


def png(color):
    out = BytesIO()
    Image.new("RGB", (8, 8), color).save(out, format="PNG")
    return out.getvalue()


def age(service, *ids):
    """Make imports older than the one-hour guard, as if they were imported yesterday."""
    with sqlite3.connect(service.path) as db:
        db.executemany("UPDATE asset_imports SET imported = imported - 86400 WHERE id=?", [(i,) for i in ids])


def product(meta):
    return {"name": meta["name"], "dimensions_m": meta["dimensions_m"], "source_id": meta["id"],
            "source_revision": meta["source_revision"]}


def design(prod=None, image_id=None, name="TEST storage"):
    packages = []
    if image_id:
        packages = [{"id": "box_1", "carton": {"name": "TEST carton", "inner_m": [0.3, 0.3, 0.3], "outer_m": [0.31, 0.31, 0.31]},
                     "graphics": [{"id": "logo", "kind": "image", "image_id": image_id}]}]
    return {"name": name, "quantity": 1, "product": prod, "packages": packages,
            "constraints": {"clearance_m": 0.02, "gap_m": 0.01, "allowed_orientations": [0], "contents": "unconfirmed"}}


def client_for(service, roles=("editor",)):
    principal = FacilityPrincipal("engineer", "tenant-a", ("site-a",), roles)
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=Path("static")))
    return TestClient(app, headers=HEADERS)


def counts(service):
    with sqlite3.connect(service.path) as db:
        return {t: db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("documents", "receipts", "create_receipts", "drafts", "quotes", "quote_attempts", "alternatives")}


def test_defaults_are_the_agreed_limits_and_can_be_changed_within_bounds(tmp_path):
    service = PackagingService(tmp_path / "store")
    assert DEFAULT_LIMITS == {"sources": 100, "source_bytes": 2 * 1024 ** 3, "images": 500, "image_bytes": 512 * MIB}
    with client_for(service) as client:
        assert "storage_limits" in client.get("/api/packaging/status").json()["capabilities"]
        assert client.get("/api/packaging/storage").json()["limits"] == DEFAULT_LIMITS
        changed = {"sources": 3, "source_bytes": 64 * MIB, "images": 2, "image_bytes": 16 * MIB}
        assert client.put("/api/packaging/storage/limits", json=changed).json()["limits"] == changed
        for bad in ({**changed, "sources": 0}, {**changed, "image_bytes": 1}, {**changed, "extra": 1}, {"sources": 3}):
            assert client.put("/api/packaging/storage/limits", json=bad).status_code == 422
    assert PackagingService(tmp_path / "store").storage(SCOPE)["limits"] == changed  # Kept with the store.


def test_a_full_workspace_refuses_new_imports_and_deletes_nothing(tmp_path):
    service = PackagingService(tmp_path / "store")
    service.set_storage_limits(SCOPE, StorageLimits(sources=2, source_bytes=64 * MIB, images=1, image_bytes=16 * MIB))
    first = source(service, "TEST a")
    source(service, "TEST b")
    assert source(service, "TEST a")["id"] == first["id"]  # The same model again adds nothing and is allowed.
    with pytest.raises(PackagingError) as full:
        source(service, "TEST c")
    assert (full.value.code, full.value.status) == ("source_storage_full", 409) and "Nothing was deleted" in full.value.message
    assert service.storage(SCOPE)["usage"]["sources"]["count"] == 2
    for i in range(3):  # Another workspace keeps its own (default) limits.
        source(service, f"TEST other {i}", scope="tenant-a/site-b")
    service.store_image(SCOPE, png("red"))
    with pytest.raises(PackagingError) as images:
        service.store_image(SCOPE, png("blue"))
    assert images.value.code == "image_storage_full"
    service.set_storage_limits(SCOPE, StorageLimits(sources=10, source_bytes=64 * MIB, images=1, image_bytes=16 * MIB))
    with pytest.raises(PackagingError) as large:
        source(service, "TEST too large", size=64 * MIB)  # The count allows it; the byte limit does not.
    assert large.value.code == "source_storage_full"
    assert service.storage(SCOPE)["usage"]["sources"]["count"] == 2


def test_remove_unused_deletes_only_what_nothing_names(tmp_path):
    service = PackagingService(tmp_path / "store")
    with client_for(service) as client:
        made = {name: source(service, f"TEST {name}") for name in ("current", "undo", "alternative", "draft", "unused", "recent")}
        logo, spare = service.store_image(SCOPE, png("red")), service.store_image(SCOPE, png("green"))
        age(service, *[m["id"] for k, m in made.items() if k != "recent"], logo["id"], spare["id"])
        doc = client.post("/api/packaging/documents", json=design(product(made["undo"]))).json()
        edit = lambda revision, request_id, body: client.put(f"/api/packaging/documents/{doc['id']}", json={
            "expected_revision": revision, "request_id": request_id, "design": body})
        assert edit(0, "test-edit-1", design(product(made["current"]), logo["id"])).status_code == 200  # "undo" is now in Undo history.
        assert client.post(f"/api/packaging/documents/{doc['id']}/alternatives", json={
            "expected_revision": 1, "request_id": "test-alt-1", "name": "TEST alt",
            "design": design(product(made["alternative"]))}).status_code == 200
        assert client.put("/api/packaging/drafts/draft_test", json={"document_id": doc["id"], "base_revision": 1,
                          "design": design(product(made["draft"])), "pending": None}).status_code == 200
        before = counts(service)
        listing = client.get("/api/packaging/storage").json()
        assert {(i["kind"], i["id"]) for i in listing["unused"]} == {("source", made["unused"]["id"]), ("image", spare["id"])}
        assert [i["id"] for i in listing["recent_unused"]] == [made["recent"]["id"]]
        removed = client.post("/api/packaging/storage/remove-unused", json={"digest": listing["unused_digest"]}).json()
        assert {i["id"] for i in removed["removed"]} == {made["unused"]["id"], spare["id"]}
        remaining = {m["id"] for m in client.get("/api/packaging/sources").json()["sources"]}
        assert remaining == {m["id"] for k, m in made.items() if k != "unused"}
        assert client.get(f"/api/packaging/images/{logo['id']}.png").status_code == 200
        assert client.get(f"/api/packaging/images/{spare['id']}.png").status_code == 404
        assert counts(service) == before  # Documents, receipts, drafts, quotes and attempts are untouched.
        replay = edit(0, "test-edit-1", design(product(made["current"]), logo["id"]))  # The same request again.
        assert replay.status_code == 200 and replay.json()["revision"] == 1  # Its receipt still answers.
        with sqlite3.connect(service.path) as db:
            assert db.execute("SELECT COUNT(*) FROM storage_removals").fetchone()[0] == 1


def test_a_stale_confirmation_removes_nothing(tmp_path):
    service = PackagingService(tmp_path / "store")
    with client_for(service) as client:
        old = source(service, "TEST old")
        age(service, old["id"])
        listing = client.get("/api/packaging/storage").json()
        newer = source(service, "TEST newer")
        age(service, newer["id"])  # A second unused model appeared after the list was shown.
        response = client.post("/api/packaging/storage/remove-unused", json={"digest": listing["unused_digest"]})
        assert (response.status_code, response.json()["error"]["code"]) == (409, "storage_changed")
        assert len(client.get("/api/packaging/sources").json()["sources"]) == 2


def test_viewers_see_storage_but_cannot_change_it(tmp_path):
    service = PackagingService(tmp_path / "store")
    with client_for(service, roles=("viewer",)) as client:
        listing = client.get("/api/packaging/storage")
        assert listing.status_code == 200
        assert client.put("/api/packaging/storage/limits", json=DEFAULT_LIMITS).status_code == 403
        assert client.post("/api/packaging/storage/remove-unused", json={"digest": listing.json()["unused_digest"]}).status_code == 403


def test_receipts_and_history_keep_their_models(tmp_path):
    """A model named only by an edit receipt (a replayable result) or by Redo history is kept."""
    service = PackagingService(tmp_path / "store")
    with client_for(service) as client:
        a, b = source(service, "TEST receipt"), source(service, "TEST redo")
        age(service, a["id"], b["id"])
        doc = client.post("/api/packaging/documents", json=design()).json()
        assert client.put(f"/api/packaging/documents/{doc['id']}", json={"expected_revision": 0, "request_id": "test-edit-a",
                          "design": design(product(a))}).status_code == 200
        assert client.put(f"/api/packaging/documents/{doc['id']}", json={"expected_revision": 1, "request_id": "test-edit-b",
                          "design": design(product(b))}).status_code == 200
        assert client.put(f"/api/packaging/documents/{doc['id']}", json={"expected_revision": 2, "request_id": "test-edit-c",
                          "design": design()}).status_code == 200
        assert client.post(f"/api/packaging/documents/{doc['id']}/undo", json={"expected_revision": 3,
                           "request_id": "test-undo-1"}).status_code == 200
        assert client.get("/api/packaging/storage").json()["unused"] == []
