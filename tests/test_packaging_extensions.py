"""Source-backed estimates, scoped artwork and reversible alternatives."""
from copy import deepcopy
from io import BytesIO
import json
import sqlite3

from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image
import pytest

from ai_inspector.facility_layout.authorization import local_facility_principal
from ai_inspector.packaging_shipping.api import create_router
from ai_inspector.packaging_shipping.catalog import catalog
from ai_inspector.packaging_shipping.models import AlternativeSave, DensityRequest, Design, Edit, RevisionCommand
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from ai_inspector.packaging_shipping.step_import import StepImportResult


def metadata():
    return {"name": "TEST solid", "format": "step", "dimensions_m": [.1, .1, .1],
            "source_revision": "a" * 64, "volume_m3": .0005,
            "physical_evidence": {"volume_basis": "closed_solid_brep"}}


def request_density():
    return DensityRequest(source_revision="a" * 64,
        material={"name": "TEST material", "density_kg_m3": 1000., "evidence": "TEST density"}, exclusions="TEST adhesive")


@pytest.fixture
def service(tmp_path):
    return PackagingService(tmp_path / "store")


def image_bytes():
    output = BytesIO()
    image = Image.new("RGBA", (100, 100))
    image.paste((255, 0, 0, 255), (30, 20, 70, 80))
    image.save(output, format="PNG")
    return output.getvalue()


def test_density_mass_requires_trusted_solid_volume_and_preserves_exclusions(service):
    source = service.store_source("scope", metadata(), b"TEST GEOMETRY")
    product = service.estimate_mass("scope", source["id"], request_density())
    assert product["mass_kg"] == pytest.approx(.5)
    assert product["mass_basis"] == "estimate"
    assert product["mass_calculation"]["exclusions"] == "TEST adhesive"
    saved = service.create("scope", Design(product=product))
    assert saved["design"]["product"] == product
    fake = deepcopy(product)
    fake["mass_calculation"]["volume_m3"] *= 2
    fake["mass_kg"] *= 2
    with pytest.raises(PackagingError, match="imported closed-solid volume"):
        service.create("scope", Design(product=fake))
    fake["source_id"] = None
    with pytest.raises(PackagingError, match="requires imported"):
        service.create("scope", Design(product=fake))
    changed = request_density().model_copy(update={"source_revision": "b"*64})
    with pytest.raises(PackagingError, match="revision"):
        service.estimate_mass("scope", source["id"], changed)
    with pytest.raises(PackagingError):
        service.estimate_mass("other", source["id"], request_density())


def test_mesh_volume_and_duplicate_source_metadata_cannot_override_evidence(service):
    meta = metadata()
    meta["format"] = "glb"
    source = service.store_source("scope", meta, b"TEST")
    with pytest.raises(PackagingError, match="no verified"):
        service.estimate_mass("scope", source["id"], request_density())
    assert service.store_source("scope", metadata(), b"REPLACEMENT") == source
    assert service.source("scope", source["id"])[1] == b"TEST"


def test_density_over_supported_mass_is_structured_not_internal_error(service):
    meta = {**metadata(), "volume_m3": 2.0, "dimensions_m": [2., 2., 2.]}
    source = service.store_source("scope", meta, b"TEST")
    with pytest.raises(PackagingError) as error:
        service.estimate_mass("scope", source["id"], request_density())
    assert error.value.code == "mass_out_of_range" and error.value.status == 422


@pytest.mark.parametrize("url", ["javascript:alert(1)", "file:///private", "https://user:password@example.com/a", "https://example.com/ bad"])
def test_supplier_sources_cannot_be_executable_or_credentialed_links(url):
    from pydantic import ValidationError
    from ai_inspector.packaging_shipping.models import Carton
    with pytest.raises(ValidationError):
        Carton(name="TEST", inner_m=[.1,.1,.1], outer_m=[.2,.2,.2], source_url=url)


def test_images_are_normalized_trimmed_and_scope_checked(service):
    image = service.store_image("scope", image_bytes())
    assert image["uv"][0] > .2 and image["uv"][2] < .8
    assert service.store_image("scope", image_bytes()) == image
    with pytest.raises(PackagingError):
        service.image("other", image["id"])
    carton = next(c for c in catalog()["cartons"] if c["id"] == "uline-s-15039")["carton"]
    design = Design(packages=[{"id": "box", "carton": carton, "graphics": [{"id": "logo", "kind": "image", "image_id": image["id"]}]}])
    document = service.create("scope", design)
    assert document["design"]["packages"][0]["graphics"][0]["image_id"] == image["id"]
    with pytest.raises(PackagingError, match="Artwork"):
        service.create("other", design)
    with pytest.raises(PackagingError):
        service.store_image("scope", b"<svg/>")


def test_alternatives_are_immutable_scoped_idempotent_and_apply_through_undo(service):
    original = service.create("scope", Design(name="Original"))
    args = AlternativeSave(expected_revision=0, request_id="save-one", name="Candidate", design=Design(name="Alternative"))
    saved = service.save_alternative("scope", original["id"], args)
    assert service.save_alternative("scope", original["id"], args) == saved
    assert service.get("scope", original["id"]) == original
    assert saved["comparison"]["shipping_cost_usd"] is None
    assert saved["comparison"]["materials_cost_usd"] is None
    with pytest.raises(PackagingError, match="request ID"):
        service.save_alternative("scope", original["id"], args.model_copy(update={"name": "Different"}))
    edited = service.change("scope", original["id"], Edit(expected_revision=0, request_id="apply-one", design=Design.model_validate(saved["design"])))
    assert edited["design"]["name"] == "Alternative"
    with pytest.raises(PackagingError, match="changed"):
        service.save_alternative("scope", original["id"], args.model_copy(update={"request_id": "stale"}))
    undone = service.change("scope", original["id"], RevisionCommand(expected_revision=1, request_id="undo-one"), "undo")
    assert undone["design"] == original["design"]
    assert service.alternatives("scope", original["id"]) == [saved]
    with pytest.raises(PackagingError):
        service.alternatives("other", original["id"])


def test_v1_migration_retains_data_and_creates_preupgrade_backup(service):
    document = service.create("scope", Design(name="TEST legacy"))
    with service.db() as db:
        db.execute("PRAGMA user_version=1")
    upgraded = PackagingService(service.root)
    assert upgraded.get("scope", document["id"])["design"] == document["design"]
    backups = list(service.root.glob("packaging-before-v2-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 1
        assert db.execute("SELECT id FROM documents").fetchone()[0] == document["id"]
    PackagingService(service.root)
    assert len(list(service.root.glob("packaging-before-v2-*.sqlite3"))) == 1


def test_catalog_has_si_conversions_and_no_fabricated_prices_or_payloads():
    entries = catalog()
    pmma = entries["materials"][0]["material"]
    assert pmma["density_kg_m3"] == 1190
    box = next(c for c in entries["cartons"] if c["id"] == "uline-s-15039")["carton"]
    assert box["inner_m"] == pytest.approx([.5588, .2032, .4572])
    assert box["tare_kg"] == pytest.approx(1.82 * .45359237)
    assert all(c["carton"]["cost_usd"] is None and c["carton"]["max_payload_kg"] is None for c in entries["cartons"])


def test_api_step_images_inventory_and_request_limits(service, monkeypatch):
    from pathlib import Path
    import ai_inspector.packaging_shipping.api as api
    class Runtime:
        max_input_bytes = 100
    async def worker(payload, **kwargs):
        assert payload == b"TEST STEP"
        return StepImportResult(json.dumps(metadata()).encode(), b"TEST GLB")
    monkeypatch.setattr(api, "import_step", worker)
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda r: local_facility_principal(site_id="test"),
        static_root=Path("static"), step_runtime=Runtime()))
    with TestClient(app, headers={"X-InspectorPro-Request": "packaging"}) as client:
        response = client.post("/api/packaging/sources/step?name=TEST", content=b"TEST STEP")
        assert response.status_code == 200, response.text
        source = response.json()
        assert client.get(f"/api/packaging/sources/{source['id']}.glb").content == b"TEST GLB"
        assert client.get(f"/api/packaging/sources/{source['id']}").json() == source
        assert client.get("/api/packaging/sources").json()["sources"] == [source]
        estimate = client.post(f"/api/packaging/sources/{source['id']}/mass-estimate", json=request_density().model_dump(mode="json"))
        assert estimate.json()["product"]["mass_kg"] == .5
        assert client.post("/api/packaging/sources/step", content=b"x"*101).status_code == 413
        image = client.post("/api/packaging/images", content=image_bytes()).json()
        assert client.get(f"/api/packaging/images/{image['id']}.png").headers["content-type"] == "image/png"
        assert client.get(f"/api/packaging/images/{image['id']}").json() == image
        assert client.post("/api/packaging/documents", content=b"x"*1048577, headers={"Content-Type": "application/json"}).status_code == 413
        assert client.get("/api/packaging/account").status_code == 403
        denied = client.put("/api/packaging/account", content=b'{"api_key":"TEST-SECRET","unexpected":true}', headers={"Content-Type": "application/json"})
        assert denied.status_code == 422 and "TEST-SECRET" not in denied.text


def test_account_endpoints_save_replace_remove_without_exposing_or_sending_key(service, tmp_path, monkeypatch):
    from pathlib import Path
    from cryptography.fernet import Fernet
    from ai_inspector.packaging_shipping.credentials import EasyPostCredentialStore
    import socket
    monkeypatch.delenv("INSPECTORPRO_PACKAGING_EASYPOST_KEY", raising=False)
    monkeypatch.setattr(socket, "create_connection", lambda *a, **k: pytest.fail("Account editing must not contact carriers"))
    cipher = Fernet(Fernet.generate_key())
    store = EasyPostCredentialStore(tmp_path / "account", "test-owner", enabled=True,
        protect=lambda raw, entropy: cipher.encrypt(raw), unprotect=lambda raw, entropy: cipher.decrypt(raw))
    app = FastAPI()
    app.include_router(create_router(service, principal_resolver=lambda r: local_facility_principal(site_id="test"),
        static_root=Path("static"), credential_factory=lambda p: store))
    secret = "EZTK_NOT_A_REAL_KEY_FOR_ENDPOINT_TEST_ONLY"
    with TestClient(app, headers={"X-InspectorPro-Request": "packaging"}) as client:
        assert client.get("/api/packaging/account").json()["configured"] is False
        saved = client.put("/api/packaging/account", json={"api_key": secret, "account_alias": "Test account"})
        assert saved.status_code == 200 and saved.json()["source"] == "secure_store"
        assert secret not in saved.text and secret not in client.get("/api/packaging/status").text
        assert secret.encode() not in store.path.read_bytes()
        invalid = client.put("/api/packaging/account", json={"api_key": secret, "account_alias": secret})
        assert invalid.status_code == 422 and secret not in invalid.text
        denied = client.put("/api/packaging/account", json={"api_key": secret, "account_alias": "Test"}, headers={"Origin": "https://other.example"})
        assert denied.status_code == 403
        removed = client.delete("/api/packaging/account")
        assert removed.json()["configured"] is False
        assert removed.json()["environment_fallback_suppressed"] is True
