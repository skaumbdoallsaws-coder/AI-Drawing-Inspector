"""Recovery checkpoints for unsaved packaging work (P5). Offline: synthetic TEST designs in throwaway stores.

A checkpoint keeps the editor's unsaved design, its base revision and any save that was in flight. It never
changes a document; the editor restores it as unsaved changes and Save validates and revises as usual."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.models import Design, DraftCheckpoint, Edit, PendingSave
from ai_inspector.packaging_shipping.service import MAX_DRAFTS, PackagingError, PackagingService

HEADERS = {"X-InspectorPro-Request": "packaging"}
OWNER, OTHER = "engineer", "reviewer"


def design(name="TEST recovery", quantity=1):
    return {"name": name, "quantity": quantity, "product": None,
            "constraints": {"clearance_m": 0.02, "gap_m": 0.01, "allowed_orientations": [0], "contents": "unconfirmed"},
            "packages": []}


def checkpoint(**fields):
    return DraftCheckpoint.model_validate({"design": design(), **fields})


def statuses(service, scope="scope-a", owner=OWNER):
    return {row["id"]: row["status"] for row in service.drafts(scope, owner)}


def test_checkpoints_report_how_unsaved_work_relates_to_saved_documents(tmp_path):
    service = PackagingService(tmp_path / "store")
    scope = "scope-a"
    # A new document's draft may be incomplete; the editor's state is kept as it was.
    service.save_draft(scope, OWNER, "draft_new", checkpoint(design=design(name="")))
    assert statuses(service) == {"draft_new": "new"}

    doc = service.create(scope, Design.model_validate(design("TEST saved")))
    edited = design("TEST saved", quantity=3)
    service.save_draft(scope, OWNER, "draft_doc", checkpoint(document_id=doc["id"], base_revision=0, design=edited,
                                                             pending={"kind": "edit", "request_id": "edit_TEST_1"}))
    assert statuses(service)["draft_doc"] == "current"
    assert service.get(scope, doc["id"])["revision"] == 0  # A checkpoint never changes the document.

    # The interrupted save lands (the editor replays it under the same request ID): the draft reports it as saved.
    service.change(scope, doc["id"], Edit(expected_revision=0, request_id="edit_TEST_1", design=Design.model_validate(edited)))
    row = next(r for r in service.drafts(scope, OWNER) if r["id"] == "draft_doc")
    assert (row["status"], row["saved_document_id"], row["current_revision"]) == ("saved", doc["id"], 1)

    # A later checkpoint for the same document replaces the earlier one; without a landed save it is behind.
    service.save_draft(scope, OWNER, "draft_doc_2", checkpoint(document_id=doc["id"], base_revision=0, design=design("TEST saved", 5)))
    assert statuses(service) == {"draft_doc_2": "behind", "draft_new": "new"}

    service.save_draft(scope, OWNER, "draft_create", checkpoint(design=design("TEST created"),
                                                                pending={"kind": "create", "request_id": "create_TEST_1"}))
    assert statuses(service)["draft_create"] == "new"
    created = service.create(scope, Design.model_validate(design("TEST created")), request_id="create_TEST_1")
    row = next(r for r in service.drafts(scope, OWNER) if r["id"] == "draft_create")
    assert (row["status"], row["saved_document_id"]) == ("saved", created["id"])

    full = service.draft(scope, OWNER, "draft_doc_2")
    assert full["design"]["quantity"] == 5 and full["base_revision"] == 0 and full["pending"] is None
    with service.db() as db:  # Simulates a store restored without that document; nothing in the app deletes one.
        db.execute("DELETE FROM documents WHERE scope=? AND id=?", (scope, doc["id"]))
    assert statuses(service)["draft_doc_2"] == "document_missing"

    assert service.remove_draft(scope, OWNER, "draft_new") == {"removed": "draft_new", "existed": True}
    assert service.remove_draft(scope, OWNER, "draft_new") == {"removed": "draft_new", "existed": False}
    with pytest.raises(PackagingError) as missing:
        service.draft(scope, OWNER, "draft_new")
    assert missing.value.code == "draft_not_found"


def test_checkpoints_belong_to_one_owner_and_scope_and_are_bounded(tmp_path):
    service = PackagingService(tmp_path / "store")
    doc = service.create("scope-a", Design.model_validate(design()))
    service.save_draft("scope-a", OWNER, "draft_a", checkpoint(document_id=doc["id"], base_revision=0))
    assert service.drafts("scope-a", OTHER) == [] and service.drafts("scope-b", OWNER) == []
    with pytest.raises(PackagingError) as foreign:
        service.save_draft("scope-b", OWNER, "draft_b", checkpoint(document_id=doc["id"], base_revision=0))
    assert foreign.value.status == 404
    for index in range(1, MAX_DRAFTS):
        service.save_draft("scope-a", OWNER, f"draft_{index}", checkpoint())
    with pytest.raises(PackagingError) as full:
        service.save_draft("scope-a", OWNER, "draft_over", checkpoint())
    assert (full.value.code, full.value.status) == ("draft_limit", 409)
    service.save_draft("scope-a", OWNER, "draft_1", checkpoint(design=design("TEST replaced")))  # Replacing is allowed.
    service.save_draft("scope-a", OTHER, "draft_other", checkpoint())  # The limit is per owner.
    assert len(service.drafts("scope-a", OWNER)) == MAX_DRAFTS


@pytest.mark.parametrize("fields", [
    {"document_id": "pkg_TEST", "base_revision": None},
    {"document_id": None, "base_revision": 0},
    {"document_id": "pkg_TEST", "base_revision": 0, "pending": {"kind": "create", "request_id": "create_TEST"}},
    {"pending": {"kind": "edit", "request_id": "edit_TEST"}},
    {"pending": {"kind": "edit", "request_id": "bad id!"}},
    {"design": {"name": "TEST", "packages": "none"}},
    {"design": {"name": "x" * 161, "packages": []}},
    {"design": {"packages": []}},
    {"unexpected": True},
])
def test_checkpoint_shape_is_checked(fields):
    with pytest.raises(ValidationError):
        DraftCheckpoint.model_validate({"design": design(), **fields})


def app_for(service, principal):
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=Path("static")))
    return TestClient(app)


def test_draft_routes_need_packaging_edit_and_leave_documents_unchanged(tmp_path):
    service = PackagingService(tmp_path / "store")
    editor = FacilityPrincipal("engineer", "tenant-a", ("site-a",), ("editor",))
    viewer = FacilityPrincipal("reviewer", "tenant-a", ("site-a",), ("viewer",))
    with app_for(service, editor) as client:
        assert "draft_recovery" in client.get("/api/packaging/status").json()["capabilities"]
        doc = client.post("/api/packaging/documents", json=design("TEST route"), headers=HEADERS).json()
        body = {"document_id": doc["id"], "base_revision": 0, "design": design("TEST route", 2),
                "pending": {"kind": "edit", "request_id": "edit_TEST_route"}}
        saved = client.put("/api/packaging/drafts/draft_route", json=body, headers=HEADERS)
        assert saved.status_code == 200 and saved.json()["id"] == "draft_route"
        listed = client.get("/api/packaging/drafts").json()
        assert "Session-only addresses, selected files and open dialogs are not kept." in listed["notice"]
        assert [(d["id"], d["status"], d["name"]) for d in listed["drafts"]] == [("draft_route", "current", "TEST route")]
        assert client.get("/api/packaging/drafts/draft_route").json()["design"]["quantity"] == 2
        assert client.get(f"/api/packaging/documents/{doc['id']}").json()["revision"] == 0
        assert client.put("/api/packaging/drafts/draft_route", json=body).status_code == 403  # Packaging client header.
        bad = client.put("/api/packaging/drafts/bad%20id!", json=body, headers=HEADERS)
        assert bad.status_code == 422 and bad.json()["error"]["code"] == "draft_id_invalid"
        oversized = client.put("/api/packaging/drafts/draft_big", json=body | {"design": design("TEST") | {"notes": "x" * 1_100_000}},
                               headers=HEADERS)
        assert oversized.status_code == 413
        assert client.delete("/api/packaging/drafts/draft_route", headers=HEADERS).json() == {"removed": "draft_route", "existed": True}
        assert client.delete("/api/packaging/drafts/draft_route", headers=HEADERS).json()["existed"] is False
    with app_for(service, viewer) as client:
        assert client.get("/api/packaging/drafts").status_code == 403
        assert client.put("/api/packaging/drafts/draft_viewer", json=body, headers=HEADERS).status_code == 403
