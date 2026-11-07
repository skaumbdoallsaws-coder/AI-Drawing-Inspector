"""Choosing an existing InspectorPro part or assembly and its configuration (P5). Offline.

Synthetic TEST library folders and throwaway stores only. Models are parsed by the real isolated GLB worker."""
from __future__ import annotations

from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pdfplumber
import pytest
import trimesh

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.library import FORMAT, InspectionLibrary
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from ai_inspector.packaging_shipping.sources import GlbRuntime

HEADERS = {"X-InspectorPro-Request": "packaging"}
RELEASE_ROOT = Path(trimesh.__file__).resolve().parents[1]


def model(extents):
    return trimesh.creation.box(extents=extents).export(file_type="glb")


def part_record(number, *, bounds=(0.1, 0.06, 0.04), configurations=(("Default", False), ("Long", True)), revision="A"):
    return {"fileName": f"{number}.SLDPRT", "units": {"internalSystem": "SI (meters)"},
            "identity": {"partNumber": number, "description": "TEST bracket", "revision": revision},
            "physical": {"mass": 1.234, "boundingBox": dict(zip(("length", "width", "height"), bounds))},
            "configurations": [{"name": name, "isActive": active} for name, active in configurations]}


@pytest.fixture
def library(tmp_path):
    root = tmp_path / "library"
    (root / "assemblies").mkdir(parents=True)
    (root / "TEST-100.json").write_text(json.dumps(part_record("TEST-100")))
    (root / "TEST-100_colored.glb").write_bytes(model([0.1, 0.06, 0.04]))
    (root / "TEST-100_feature_colors.json").write_text("{}")  # A sidecar, not an entry.
    (root / "TEST-BAD.json").write_text(json.dumps(part_record("TEST-BAD")))
    (root / "TEST-BAD_colored.glb").write_bytes(model([0.2, 0.06, 0.04]))  # Disagrees with its own record.
    (root / "TEST-ORPHAN_colored.glb").write_bytes(model([0.1, 0.1, 0.1]))  # A model without its record.
    (root / "assemblies" / "TEST-ASM_assembly.json").write_text(json.dumps(
        {"identity": {"assemblyNumber": "TEST-ASM", "description": "TEST pair", "revision": "B"}, "components": []}))
    (root / "assemblies" / "TEST-ASM_colored.glb").write_bytes(model([0.3, 0.1, 0.05]))
    return root


def client_for(service, root, roles=("editor",)):
    principal = FacilityPrincipal("engineer", "tenant-a", ("site-a",), roles)
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=Path("static"),
                                     source_runtime=GlbRuntime(RELEASE_ROOT), library_root=root))
    return TestClient(app, headers=HEADERS)


def listed(client, **params):
    return {(e["kind"], e["id"]): e for e in client.get("/api/packaging/library", params=params).json()["entries"]}


def choose(client, entry, configuration):
    return client.post("/api/packaging/sources/library", json={
        "kind": entry["kind"], "id": entry["id"], "revision": entry["revision"], "configuration": configuration,
        "record_sha256": entry["record_sha256"]})


def design(product=None):
    return {"name": "TEST library product", "quantity": 1, "product": product,
            "constraints": {"clearance_m": 0.02, "gap_m": 0.01, "allowed_orientations": [0], "contents": "unconfirmed"},
            "packages": []}


def test_library_lists_entries_with_a_model_and_their_configurations(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        assert "library_sources" in client.get("/api/packaging/status").json()["capabilities"]
        response = client.get("/api/packaging/library")
        entries = listed(client)
        assert set(entries) == {("part", "TEST-100"), ("part", "TEST-BAD"), ("assembly", "TEST-ASM")}
        part = entries["part", "TEST-100"]
        assert part["configurations"] == [{"name": "Default", "active": False, "available": False},
                                          {"name": "Long", "active": True, "available": True}]
        assert (part["revision"], part["extracted_bounds_m"], part["importable"]) == ("A", [0.1, 0.06, 0.04], True)
        assert part["record_sha256"] == sha256((library / "TEST-100.json").read_bytes()).hexdigest()
        # Assembly extractions record no configuration name: the model is offered as extracted.
        assert entries["assembly", "TEST-ASM"]["configurations"] == [{"name": "", "active": True, "available": True}]
        assert tmp_path.name not in response.text and "fileName" not in response.text  # No paths reach the browser.
        assert set(listed(client, kind="assembly")) == {("assembly", "TEST-ASM")}
        assert set(listed(client, q="bad")) == {("part", "TEST-BAD")}


def test_the_active_configuration_imports_a_copy_bound_to_its_library_entry(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        entry = listed(client)["part", "TEST-100"]
        response = choose(client, entry, "Long")
        assert response.status_code == 200, response.text
        meta = response.json()
        assert meta["name"] == "Part TEST-100 rev A - TEST bracket (Long)"
        assert sorted(meta["dimensions_m"], reverse=True) == pytest.approx([0.1, 0.06, 0.04])
        assert (meta["mass_kg"], meta["mass_basis"]) == (None, "unknown")  # The record's 1.234 kg is not imported.
        assert meta["library"] == {"format": FORMAT, "kind": "part", "id": "TEST-100", "revision": "A", "configuration": "Long",
                                   "record_sha256": entry["record_sha256"],
                                   "model_sha256": sha256((library / "TEST-100_colored.glb").read_bytes()).hexdigest()}
        assert "agrees with the extracted SOLIDWORKS bounding box" in meta["geometry_evidence"]
        product = {"name": meta["name"], "dimensions_m": meta["dimensions_m"], "source_id": meta["id"],
                   "source_revision": meta["source_revision"]}
        saved = client.post("/api/packaging/documents", json=design(product))
        assert saved.status_code == 200, saved.text
        # Imported dimensions stay locked, as for any imported source.
        changed = dict(product, dimensions_m=[0.09, 0.06, 0.04])
        refused = client.put(f"/api/packaging/documents/{saved.json()['id']}",
                             json={"expected_revision": 0, "request_id": "test-edit-1", "design": design(changed)})
        assert (refused.status_code, refused.json()["error"]["code"]) == (409, "source_changed")
        assembly = choose(client, listed(client)["assembly", "TEST-ASM"], "")
        assert assembly.status_code == 200, assembly.text
        assert assembly.json()["name"] == "Assembly TEST-ASM rev B - TEST pair"
        assert "records no bounding box to cross-check" in assembly.json()["geometry_evidence"]


def test_unextracted_or_unknown_configurations_are_refused(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        entry = listed(client)["part", "TEST-100"]
        for configuration, status, code in [("Default", 409, "library_configuration_not_extracted"),
                                            ("Missing", 404, "library_configuration_unknown")]:
            response = choose(client, entry, configuration)
            assert (response.status_code, response.json()["error"]["code"]) == (status, code)
        assert "Make Default active in SOLIDWORKS" in choose(client, entry, "Default").json()["error"]["message"]
        assert client.get("/api/packaging/sources").json()["sources"] == []


def test_an_entry_that_changed_after_listing_is_refused(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        entry = listed(client)["part", "TEST-100"]
        (library / "TEST-100.json").write_text(json.dumps(part_record("TEST-100", revision="B")))
        response = choose(client, entry, "Long")
        assert (response.status_code, response.json()["error"]["code"]) == (409, "library_source_changed")
        assert client.get("/api/packaging/sources").json()["sources"] == []


def test_requests_name_entries_only(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        entry = listed(client)["part", "TEST-100"]
        for bad in ("../TEST-100", "TEST-100/x", "..", "a\\b", "", "-x"):
            assert choose(client, dict(entry, id=bad), "Long").status_code == 422, bad
        extra = client.post("/api/packaging/sources/library", json={"kind": "part", "id": "TEST-100", "revision": "A",
                            "configuration": "Long", "record_sha256": entry["record_sha256"], "path": str(library)})
        assert extra.status_code == 422
        for missing in ("TEST-999", "TEST-ORPHAN"):
            response = choose(client, dict(entry, id=missing), "Long")
            assert (response.status_code, response.json()["error"]["code"]) == (404, "library_entry_not_found")


def test_a_model_that_disagrees_with_its_record_is_not_imported(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        response = choose(client, listed(client)["part", "TEST-BAD"], "Long")
        assert (response.status_code, response.json()["error"]["code"]) == (422, "library_geometry_mismatch")
        assert client.get("/api/packaging/sources").json()["sources"] == []


def test_viewers_can_list_but_not_import(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library, roles=("viewer",)) as client:
        entry = listed(client)["part", "TEST-100"]
        assert choose(client, entry, "Long").status_code == 403


def test_library_status_follows_the_library(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        meta = choose(client, listed(client)["part", "TEST-100"], "Long").json()
        status = lambda: client.get(f"/api/packaging/sources/{meta['id']}/library-status").json()["status"]
        assert status() == "current"
        (library / "TEST-100_colored.glb").write_bytes(model([0.1, 0.06, 0.05]))
        assert status() == "changed"
        (library / "TEST-100.json").unlink()
        assert status() == "unavailable"
        upload = client.post("/api/packaging/sources", params={"meters_per_unit": "1"}, content=model([0.1, 0.1, 0.1])).json()
        response = client.get(f"/api/packaging/sources/{upload['id']}/library-status")
        assert (response.status_code, response.json()["error"]["code"]) == (409, "library_source_required")


def test_the_same_model_uploaded_and_chosen_keeps_both_provenances(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        upload = client.post("/api/packaging/sources", params={"meters_per_unit": "1"},
                             content=(library / "TEST-100_colored.glb").read_bytes()).json()
        chosen = choose(client, listed(client)["part", "TEST-100"], "Long").json()
        assert upload["id"] != chosen["id"] and "library" not in upload and chosen["library"]["id"] == "TEST-100"
        assert len(client.get("/api/packaging/sources").json()["sources"]) == 2


def test_without_a_library_the_routes_say_so(tmp_path):
    with client_for(PackagingService(tmp_path / "store"), None) as client:
        assert "library_sources" not in client.get("/api/packaging/status").json()["capabilities"]
        response = client.get("/api/packaging/library")
        assert (response.status_code, response.json()["error"]["code"]) == (503, "library_unavailable")


def test_report_names_the_library_entry_and_its_evidence(tmp_path, library):
    with client_for(PackagingService(tmp_path / "store"), library) as client:
        meta = choose(client, listed(client)["part", "TEST-100"], "Long").json()
        doc = client.post("/api/packaging/documents", json=design({
            "name": meta["name"], "dimensions_m": meta["dimensions_m"], "source_id": meta["id"],
            "source_revision": meta["source_revision"]})).json()
        payload = client.get(f"/api/packaging/documents/{doc['id']}/report.pdf", params={"revision": 0})
        assert payload.status_code == 200
        with pdfplumber.open(BytesIO(payload.content)) as reader:
            text = " ".join(" ".join((page.extract_text() or "") for page in reader.pages).split())  # Wrapped lines rejoined.
        assert "InspectorPro library part TEST-100" in text and "Configuration: Long" in text
        assert "agrees with the extracted SOLIDWORKS" in text


def test_large_models_are_listed_but_not_importable_and_parts_without_an_active_configuration(tmp_path, library):
    small = InspectionLibrary(library, max_model_bytes=64)
    entry = next(e for e in small.entries("part")["entries"] if e["id"] == "TEST-100")
    assert (entry["importable"], "import limit" in entry["reason"]) == (False, True)
    with pytest.raises(PackagingError) as refused:
        small.model("part", "TEST-100", "A", "Long", entry["record_sha256"])
    assert (refused.value.code, refused.value.status) == ("library_model_unavailable", 413)
    (library / "TEST-100.json").write_text(json.dumps(part_record("TEST-100", configurations=(("Default", False),))))
    configurations = InspectionLibrary(library, max_model_bytes=1 << 24).entries("part", "TEST-100")["entries"][0]["configurations"]
    assert configurations == [{"name": "", "active": True, "available": True},
                              {"name": "Default", "active": False, "available": False}]
