"""The contents declaration (classification, basis, evidence) belongs to the user. The user's editor, the HTTP routes,
saves a contents change only with the user's explicit confirmation; Sage's tools never change it (see
tests/test_codex_packaging_tools.py). Offline: the pilot app on temporary storage, no carrier key, no network."""
from __future__ import annotations

import ast
from pathlib import Path
import re

from fastapi.testclient import TestClient
import pytest

from ai_inspector.facility_layout import authorization
from ai_inspector.packaging_shipping.models import Design
from ai_inspector.packaging_shipping.service import PackagingError, guard_contents
from tools.run_packaging_pilot import create_app

ROOT = Path(__file__).resolve().parents[1]
HEADERS = {"x-inspectorpro-request": "packaging"}
ORDINARY = {"contents": "ordinary_nonhazardous", "basis": "product_declaration", "evidence": "TEST declaration"}
CALL = re.compile(r"service\s*\.\s*(create|change|save_alternative)\s*\(", re.IGNORECASE)


def design(contents="unconfirmed", basis="", evidence="", name="TEST contents guard"):
    return {"name": name, "quantity": 1,
            "product": {"name": "TEST product", "dimensions_m": [0.1, 0.08, 0.04], "mass_kg": 0.5,
                        "mass_basis": "user_measured", "mass_evidence": "TEST scale"},
            "constraints": {"contents": contents, "contents_basis": basis, "contents_evidence": evidence}}


@pytest.fixture
def client(tmp_path, monkeypatch):
    principal = authorization.FacilityPrincipal("tester", "tenant-a", ("test-site",), ("editor",))
    monkeypatch.setattr(authorization, "local_facility_principal", lambda **kwargs: principal)
    with TestClient(create_app(storage=tmp_path / "pilot-only"), base_url="http://127.0.0.1:8179", headers=HEADERS) as c:
        yield c


def refused(response):
    assert response.status_code == 409, response.text
    error = response.json()["error"]
    assert error["code"] == "contents_confirmation_required", error
    assert "Only you can classify the contents" in error["message"] and "Nothing was saved" in error["message"]
    return error["message"]


def edit(client, doc, revision, body, request_id, **extra):
    return client.put(f"/api/packaging/documents/{doc}",
                      json={"expected_revision": revision, "request_id": request_id, "design": body, **extra})


def test_creating_with_classified_contents_needs_the_users_confirmation(client):
    message = refused(client.post("/api/packaging/documents", json=design(**ORDINARY)))
    assert ("sets the contents to Ordinary, non-hazardous, declaration about the real product; they are now "
            "Not confirmed.") in message
    assert client.get("/api/packaging/documents").json()["documents"] == []
    created = client.post("/api/packaging/documents?contents_confirmed=true", json=design(**ORDINARY))
    assert created.status_code == 200 and created.json()["design"]["constraints"]["contents"] == "ordinary_nonhazardous"
    assert client.post("/api/packaging/documents", json=design()).status_code == 200  # Unclassified: no question.


def test_editing_the_contents_needs_the_users_confirmation_and_names_the_change(client):
    doc = client.post("/api/packaging/documents", json=design()).json()["id"]
    assert "sets the contents to Ordinary, non-hazardous" in refused(edit(client, doc, 0, design(**ORDINARY), "edit-1"))
    assert client.get(f"/api/packaging/documents/{doc}").json()["revision"] == 0
    assert edit(client, doc, 0, design(**ORDINARY), "edit-1", contents_confirmed=True).json()["revision"] == 1
    newer = design(**{**ORDINARY, "evidence": "TEST newer declaration"})
    assert "replaces the evidence for the contents" in refused(edit(client, doc, 1, newer, "edit-2"))
    # Any other change saves without a question; the confirmation must be a real boolean.
    assert edit(client, doc, 1, design(**ORDINARY, name="TEST renamed"), "edit-3").json()["revision"] == 2
    assert edit(client, doc, 2, newer, "edit-4", contents_confirmed="yes").status_code == 422


def test_undo_and_redo_that_change_the_contents_need_the_users_confirmation(client):
    doc = client.post("/api/packaging/documents", json=design()).json()["id"]
    edit(client, doc, 0, design(**ORDINARY), "edit-1", contents_confirmed=True)

    def step(action, revision, request_id, **extra):
        return client.post(f"/api/packaging/documents/{doc}/{action}",
                           json={"expected_revision": revision, "request_id": request_id, **extra})
    assert "sets the contents to Not confirmed" in refused(step("undo", 1, "undo-1"))
    assert step("undo", 1, "undo-1", contents_confirmed=True).json()["revision"] == 2
    refused(step("redo", 2, "redo-1"))
    redone = step("redo", 2, "redo-1", contents_confirmed=True).json()
    assert redone["revision"] == 3 and redone["design"]["constraints"]["contents"] == "ordinary_nonhazardous"


def test_saving_an_alternative_with_other_contents_needs_the_users_confirmation(client):
    doc = client.post("/api/packaging/documents", json=design()).json()["id"]
    path = f"/api/packaging/documents/{doc}/alternatives"
    body = {"expected_revision": 0, "request_id": "alt-1", "name": "TEST ordinary", "design": design(**ORDINARY)}
    refused(client.post(path, json=body))
    assert client.get(path).json()["alternatives"] == []
    assert client.post(path, json={**body, "contents_confirmed": True}).status_code == 200
    # A snapshot of the saved design changes nothing, so it needs no question.
    assert client.post(path, json={"expected_revision": 0, "request_id": "alt-2", "name": "TEST snapshot"}).status_code == 200


def test_the_guard_refuses_sage_and_unconfirmed_users_before_any_write():
    before, after = Design(), Design.model_validate(design(**ORDINARY))
    guard_contents(before, after, "direct", False)  # In-process callers: tests and tools.
    guard_contents(before, before, "sage", False)   # Unchanged contents: nothing to guard.
    with pytest.raises(PackagingError) as sage:
        guard_contents(before, after, "sage", True)
    assert sage.value.code == "contents_change_needs_user" and sage.value.status == 403
    for confirmed in (False, "true", 1):
        with pytest.raises(PackagingError) as user:
            guard_contents(before, after, "user", confirmed)
        assert user.value.code == "contents_confirmation_required"
    guard_contents(before, after, "user", True)
    with pytest.raises(ValueError):
        guard_contents(before, after, "codex", True)


def test_every_production_editing_call_names_its_author():
    """Every production call that saves a design names its author: the user's routes "user", Sage "sage". None may
    rely on the in-process "direct" default, which skips the guard and is meant for tests only."""
    methods = ("create", "change", "save_alternative")
    files = [ROOT / "server.py"] + [path for base in ("ai_inspector", "tools", "desktop") for path in (ROOT / base).rglob("*.py")
                                    if not set(path.relative_to(ROOT).parts) & {"tests", "node_modules", "__pycache__", ".runtime"}]
    found = {}
    for path in files:
        text = path.read_text(encoding="utf-8-sig", errors="replace")  # server.py starts with a byte-order mark.
        if not CALL.search(text):  # Parse only files that call one of the methods on a service.
            continue
        for node in ast.walk(ast.parse(text)):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in methods
                    and ast.unparse(node.func.value).split(".")[-1].lower().endswith("service")):
                name = path.relative_to(ROOT).as_posix()
                author = {k.arg: k.value for k in node.keywords}.get("author")
                assert isinstance(author, ast.Constant) and author.value in {"user", "sage"}, (name, ast.unparse(node))
                found.setdefault(name, []).append(author.value)
    assert found == {"ai_inspector/packaging_shipping/api.py": ["user"] * 5,
                     "ai_inspector/codex_runtime/packaging_tools.py": ["sage"]}
