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


def unapplied(**fields):
    return {"editor": "carton", "package_id": "box_1", "fields": [["carton_name", "TEST typed, not applied"], ["inner_0", "31"],
                                                                  ["inner_0", "32"], ["fragile", True]], **fields}


def test_unapplied_fields_and_an_unfinished_import_are_kept_as_typed(tmp_path):
    """Values typed but not applied come back exactly, in form order (repeated names kept); nothing applies them."""
    service = PackagingService(tmp_path / "store")
    scope = "scope-a"
    importing = {"kind": "glb", "name": "TEST bracket.glb", "started_at": 1_800_000_000.5}
    service.save_draft(scope, OWNER, "draft_typed", checkpoint(unapplied=unapplied(), importing=importing))
    listed = service.drafts(scope, OWNER)[0]
    assert (listed["unapplied_fields"], listed["unapplied_editor"], listed["importing"], listed["import_result"]) == (
        4, "carton", {**importing, "library": None}, None)
    assert "unapplied" not in listed and "TEST typed" not in str(listed)  # A summary; only the draft carries typed values.
    assert service.draft(scope, OWNER, "draft_typed")["unapplied"] == unapplied(component_id=None, graphic_id=None)
    service.save_draft(scope, OWNER, "draft_plain", checkpoint())
    plain = next(row for row in service.drafts(scope, OWNER) if row["id"] == "draft_plain")
    assert (plain["unapplied_fields"], plain["unapplied_editor"], plain["importing"], plain["import_result"]) == (0, None, None, None)
    assert plain["design_changed"] is None  # New: nothing saved to compare with.


def test_a_draft_says_whether_its_design_differs_from_the_saved_document(tmp_path):
    """A draft kept only for typed values or an unfinished import is not described as unsaved design changes."""
    service = PackagingService(tmp_path / "store")
    scope = "scope-a"
    product = {"name": "TEST block", "dimensions_m": [0.1, 0.2, 0.3], "mass_kg": 2.0, "mass_basis": "user_measured",
               "mass_evidence": "TEST scale reading"}
    doc = service.create(scope, Design.model_validate(design("TEST saved") | {"product": product}))
    same = service.get(scope, doc["id"])["design"]
    same["product"]["mass_kg"] = 2  # A browser sends a whole-number float back as 2, not 2.0.
    service.save_draft(scope, OWNER, "draft_same", checkpoint(document_id=doc["id"], base_revision=0, design=same,
                                                              importing={"kind": "glb", "name": "TEST.glb", "started_at": 1.0}))
    row = service.drafts(scope, OWNER)[0]
    assert (row["status"], row["design_changed"]) == ("current", False)
    service.save_draft(scope, OWNER, "draft_same", checkpoint(document_id=doc["id"], base_revision=0, design=design("TEST saved", 2)))
    assert service.drafts(scope, OWNER)[0]["design_changed"] is True


@pytest.mark.parametrize("fields", [
    {"unapplied": unapplied(editor="rates")},  # Address fields are session-only and never kept.
    {"unapplied": unapplied(fields=[["bad name", "x"]])},
    {"unapplied": unapplied(fields=[["carton_name", "x" * 4001]])},
    {"unapplied": unapplied(fields=[["carton_name", "x"]] * 301)},
    {"importing": {"kind": "library", "name": "TEST", "started_at": 1.0}},  # A library import names its entry.
    {"importing": {"kind": "glb", "name": "", "started_at": 1.0}},
    {"importing": {"kind": "glb", "name": "TEST", "started_at": 1.0, "path": "C:/private/model.glb"}},
])
def test_unapplied_and_import_records_are_bounded(fields):
    with pytest.raises(ValidationError):
        checkpoint(**fields)


def test_an_interrupted_import_reports_the_model_it_stored_after_it_started(tmp_path):
    import sqlite3
    from hashlib import sha256
    service = PackagingService(tmp_path / "store")
    scope = "scope-a"

    def stored(name, library=None, at=None):
        meta = {"name": name, "dimensions_m": [0.1, 0.06, 0.04], "source_revision": sha256(name.encode()).hexdigest(),
                "mass_basis": "unknown", "mass_kg": None, **({"library": library} if library else {})}
        made = service.store_source(scope, meta, b"G" * 64)
        if at is not None:
            with sqlite3.connect(service.path) as db:
                db.execute("UPDATE asset_imports SET imported=? WHERE id=?", (at, made["id"]))
        return made

    entry = {"kind": "part", "id": "TEST-100", "revision": "A", "configuration": "Long", "record_sha256": "a" * 64}
    older = stored("TEST bracket.glb", at=1_000.0)  # The same name, imported before this import started.
    service.save_draft(scope, OWNER, "draft_file", checkpoint(importing={"kind": "glb", "name": "TEST bracket.glb", "started_at": 2_000.0}))
    service.save_draft(scope, OWNER, "draft_library", checkpoint(importing={"kind": "library", "name": "Part TEST-100 rev A",
                                                                          "started_at": 2_000.0, "library": entry}))
    rows = {row["id"]: row for row in service.drafts(scope, OWNER)}
    assert rows["draft_file"]["import_result"] is None and rows["draft_library"]["import_result"] is None
    stored("TEST other.glb", at=2_010.0)  # Finished after the start, but a different file.
    finished = stored("TEST bracket.glb ", at=2_020.0)  # The STEP route trims names; both spellings match.
    by_library = stored("Part TEST-100 rev A - TEST bracket (Long)", library={**entry, "format": "inspectorpro-inspection-library/v1"}, at=2_030.0)
    rows = {row["id"]: row for row in service.drafts(scope, OWNER)}
    assert rows["draft_file"]["import_result"] is None or rows["draft_file"]["import_result"]["id"] != older["id"]
    assert rows["draft_library"]["import_result"] == {"id": by_library["id"], "name": by_library["name"]}
    service.save_draft(scope, OWNER, "draft_file", checkpoint(importing={"kind": "glb", "name": "TEST bracket.glb ", "started_at": 2_000.0}))
    assert {row["id"]: row for row in service.drafts(scope, OWNER)}["draft_file"]["import_result"]["id"] == finished["id"]
    assert all(row["import_result"] is None for row in service.drafts("scope-b", OWNER))  # Never another workspace's model.
