"""Missing optional components (P5). Offline: throwaway stores, synthetic TEST designs, no network.

Each optional component disables one feature. A missing one is reported as unavailable in this installation, never
as a bad file or a server fault, and the status lists it. The GLB parser runs in the real isolated worker with an
empty dependency root; the in-process arrangement solver and PDF library are blocked at import."""
from __future__ import annotations

import asyncio
import builtins
from pathlib import Path
import sys

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
import trimesh

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.catalog import catalog
from ai_inspector.packaging_shipping.packing import propose
from ai_inspector.packaging_shipping.report import render_report
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from ai_inspector.packaging_shipping.sources import GlbRuntime, import_glb_isolated

HEADERS = {"X-InspectorPro-Request": "packaging"}
RELEASE_ROOT = Path(trimesh.__file__).resolve().parents[1]  # The runtime these tests run with: complete.
MISSING = {"glb_import_runtime_missing", "arrangement_runtime_missing", "pdf_report_runtime_missing"}


@pytest.fixture
def blocked(monkeypatch):
    """Make the named top-level packages unimportable for this test, as if they were not installed."""
    def block(*names):
        real = builtins.__import__

        def guarded(name, *args, **kwargs):
            if name.split(".")[0] in names:
                raise ModuleNotFoundError(f"No module named {name!r}", name=name)
            return real(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guarded)
        for name in names:
            monkeypatch.setitem(sys.modules, name, None)
    return block


def design():
    return {"name": "TEST components", "quantity": 1, "product": None,
            "constraints": {"clearance_m": 0.02, "gap_m": 0.01, "allowed_orientations": [0], "contents": "unconfirmed"},
            "packages": []}


def test_glb_worker_reports_a_missing_parser_component_not_a_bad_file(tmp_path):
    empty = tmp_path / "empty-dependencies"
    empty.mkdir()
    payload = trimesh.creation.box(extents=[0.1, 0.06, 0.04]).export(file_type="glb")
    with pytest.raises(PackagingError) as missing:
        asyncio.run(import_glb_isolated(payload, "TEST", 1.0, tmp_path / "state", runtime=GlbRuntime(empty)))
    assert (missing.value.code, missing.value.status) == ("source_runtime_unavailable", 503)
    assert "Manual dimensions still work" in missing.value.message
    # With its components present, a bad file is still reported as a bad file.
    with pytest.raises(PackagingError) as invalid:
        asyncio.run(import_glb_isolated(b"x" * 64, "TEST", 1.0, tmp_path / "state", runtime=GlbRuntime(RELEASE_ROOT)))
    assert (invalid.value.code, invalid.value.status) == ("source_invalid", 422)
    assert list((tmp_path / "state" / "import-jobs").iterdir()) == []


def test_in_process_components_fail_with_a_feature_message(blocked):
    blocked("py3dbp", "reportlab")
    with pytest.raises(PackagingError) as solver:
        propose(None, [])
    assert (solver.value.code, solver.value.status) == ("arrangement_unavailable", 503)
    assert "Manual packing still works" in solver.value.message
    with pytest.raises(PackagingError) as pdf:
        render_report({}, (), ())
    assert (pdf.value.code, pdf.value.status) == ("report_unavailable", 503)


def app_for(service, runtime):
    principal = FacilityPrincipal("engineer", "tenant-a", ("site-a",), ("editor",))
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda request: principal, static_root=Path("static"),
                                     source_runtime=runtime))
    return TestClient(app, headers=HEADERS)


def test_status_lists_missing_components_and_routes_answer_clearly(tmp_path, blocked):
    service = PackagingService(tmp_path / "store")
    with app_for(service, GlbRuntime(RELEASE_ROOT)) as client:
        assert not MISSING & set(client.get("/api/packaging/status").json()["unsupported"])
    empty = tmp_path / "empty-dependencies"
    empty.mkdir()
    blocked("py3dbp", "reportlab")
    with app_for(service, GlbRuntime(empty)) as client:
        status = client.get("/api/packaging/status").json()
        assert MISSING <= set(status["unsupported"])
        doc = client.post("/api/packaging/documents", json=design()).json()
        carton = catalog()["cartons"][0]["carton"]
        answers = {
            "arrangement_unavailable": client.post(f"/api/packaging/documents/{doc['id']}/arrangements",
                                                   json={"expected_revision": 0, "cartons": [carton]}),
            "report_unavailable": client.get(f"/api/packaging/documents/{doc['id']}/report.pdf", params={"revision": 0}),
            "source_runtime_unavailable": client.post("/api/packaging/sources", params={"meters_per_unit": "1"},
                                                      content=b"x" * 64),
        }
        for code, response in answers.items():
            assert (response.status_code, response.json()["error"]["code"]) == (503, code), response.text
        assert client.get(f"/api/packaging/documents/{doc['id']}").json()["revision"] == 0
