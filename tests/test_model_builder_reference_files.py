"""Contained MB5b intake, scoped retention, and draft comparison contracts."""
from io import BytesIO
import base64
from pathlib import Path
import asyncio
import importlib.util
import json
import time

import pytest
from PIL import Image, PngImagePlugin

from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.model_import_runtime import model_import_runtime
from ai_inspector.facility_layout.reference_files import ReferenceStore
from ai_inspector.industrial_assets.model_builder.errors import ModelBuildError
from ai_inspector.industrial_assets.model_reference_runner import run_reference
from tests.model_builder_test_support import recipe
from tests.test_model_builder_registration import context


def png(*, frames=False, metadata=False):
    image = Image.new("RGB", (48, 30), "#cc4455")
    output = BytesIO()
    if frames:
        image.save(output, format="PNG", save_all=True,
                   append_images=[Image.new("RGB", image.size, "#225588")], duration=50)
    else:
        note = PngImagePlugin.PngInfo()
        if metadata:
            note.add_text("Comment", "private location")
        image.save(output, format="PNG", pnginfo=note)
    return output.getvalue()


def upload(store, scope, payload, name="image.jpg"):
    item = store.begin_upload(scope, name, len(payload))
    try:
        item.write(payload)
        identifier = item.finish()["referenceId"]
    finally:
        item.abort()
    for _ in range(200):
        state = store.get(scope, identifier)["state"]
        if state != "processing":
            break
        time.sleep(.05)
    return identifier, store.get(scope, identifier)


@pytest.fixture
def references(context):
    c = context
    store = ReferenceStore(c.host.service, dependency_root=model_import_runtime().dependency_root)
    c.host.service._reference_store = store
    return c, store


def test_image_content_metadata_and_one_frame_policy(references):
    c, store = references
    identifier, record = upload(store, c.scope, png(metadata=True), "misnamed.jpg")
    assert record["state"] == "ready" and record["kind"] == "image" and record["pages"] == 1
    picture, _ = store.page(c.scope, identifier, 0)
    with Image.open(BytesIO(picture)) as clean:
        assert clean.size == (48, 30) and clean.getpixel((2, 2))[:3] == (204, 68, 85)
        assert "Comment" not in clean.info and not clean.getexif()
    gif = store.begin_upload(c.scope, "sample.gif", 38)
    gif.write(b"GIF89a" + b"\0"*32)
    with pytest.raises(FacilityLayoutError) as caught:
        gif.finish()
    assert caught.value.code == "reference_invalid"
    gif.abort()
    _, failed = upload(store, c.scope, png(frames=True))
    assert failed["state"] == "failed" and failed["refusal"]["code"] == "reference_invalid"


def test_exif_gps_is_removed_by_worker(references):
    c, store = references
    image = Image.new("RGB", (30, 20), "#5588aa")
    exif = Image.Exif()
    exif[34853] = {1: "N", 2: (1, 2, 3), 3: "E", 4: (4, 5, 6)}
    exif[274] = 6
    output = BytesIO()
    image.save(output, format="JPEG", exif=exif)
    identifier, record = upload(store, c.scope, output.getvalue(), "photo.png")
    assert record["state"] == "ready"
    picture, _ = store.page(c.scope, identifier)
    with Image.open(BytesIO(picture)) as clean:
        assert clean.size == (20, 30)
        assert not clean.getexif() and "exif" not in clean.info


def test_image_long_side_is_bounded(references):
    c, store = references
    source = BytesIO()
    Image.new("RGB", (2300, 30), "#445566").save(source, format="WEBP")
    identifier, record = upload(store, c.scope, source.getvalue(), "photo.webp")
    assert record["state"] == "ready"
    with Image.open(BytesIO(store.page(c.scope, identifier)[0])) as clean:
        assert max(clean.size) == 2048


def test_pdf_is_disabled_by_default_and_upload_admission_is_bounded(references, monkeypatch):
    c, store = references
    item = store.begin_upload(c.scope, "sheet.jpg", 8)
    item.write(b"%PDF-1.7")
    with pytest.raises(FacilityLayoutError, match="PDF reading is not enabled"):
        item.finish()
    item.abort()
    with pytest.raises(FacilityLayoutError) as caught:
        store.begin_upload(c.scope, "big.png", 25*1024*1024+1)
    assert caught.value.code == "reference_limit"
    import ai_inspector.facility_layout.reference_files as module
    monkeypatch.setattr(module, "SITE_BYTES", 75*1024*1024)
    first = store.begin_upload(c.scope, "first.png", 10)
    try:
        with pytest.raises(FacilityLayoutError) as caught:
            store.begin_upload(c.scope, "second.png", 10)
        assert caught.value.code == "reference_quota"
    finally:
        first.abort()


def test_reference_count_quota_is_checked_before_upload(references):
    c, store = references
    from ai_inspector.facility_layout import model_import_files as disk
    for index in range(100):
        identifier = f"rf-{index:024x}"
        disk.atomic(store._path(c.scope, identifier), {"referenceId": identifier})
    with pytest.raises(FacilityLayoutError) as caught:
        store.begin_upload(c.scope, "one-more.png", 8)
    assert caught.value.code == "reference_quota"


def test_scope_pin_registration_and_sweep(references):
    c, store = references
    identifier, record = upload(store, c.scope, png())
    from ai_inspector.facility_layout.authorization import FacilityPrincipal
    from ai_inspector.facility_layout.model_import_store import ModelImportScope
    viewer = FacilityPrincipal("viewer", c.principal.tenant_id, (c.scope.site_id,), ("viewer",))
    view_scope = ModelImportScope(viewer, c.scope.site_id, c.scope.layout_id)
    assert store.get(view_scope, identifier)["state"] == "ready"
    with pytest.raises(FacilityLayoutError):
        store.begin_upload(view_scope, "forbidden.png", 8)
    store.pin(c.scope, [identifier], "md-"+"a"*24)
    folder = store._folder(c.scope)
    path = folder / "records" / (identifier + ".json")
    from ai_inspector.facility_layout import model_import_files as disk
    raw = disk.read_json(path)
    raw["created"] -= 8*86400
    disk.atomic(path, raw)
    assert store.page(c.scope, identifier)[0].startswith(b"\x89PNG")  # A pin protects the old reference.
    store.sweep()
    with pytest.raises(FacilityLayoutError) as caught:
        store.page(c.scope, identifier)
    assert caught.value.code == "reference_missing"
    assert not any(item["referenceId"] == identifier for item in store.list(c.scope))
    # An absent/expired draft releases its pin and the old file in one sweep.
    with pytest.raises(FacilityLayoutError) as caught:
        store.get(c.scope, identifier)
    assert caught.value.code == "reference_missing"
    other = c.host.principal()
    foreign = ModelImportScope(other, "another-site", c.scope.layout_id)
    with pytest.raises(FacilityLayoutError):
        store.get(foreign, identifier)


def test_build_pins_reference_comparison_and_registered_provenance(references):
    c, store = references
    identifier, _ = upload(store, c.scope, png())
    request = recipe()
    summary, picture = c.host.agent_runtime.model_builder_build(
        c.principal, c.reference, {**request, "compareWith": {"referenceId": identifier}})
    assert picture.startswith(b"\x89PNG")
    with Image.open(BytesIO(picture)) as image:
        assert image.size == (1536, 768)
    assert len(picture) <= 1536*1024
    frozen = c.store.draft(c.scope, summary["draftId"])
    assert frozen["recipe"]["references"] == []
    assert store.draft_references(c.scope, summary["draftId"]) == [identifier]
    portable = json.loads((c.store._folder(c.scope) / "drafts" / summary["draftId"] /
                           "recipe.json").read_bytes())
    assert "references" not in portable
    from ai_inspector.industrial_assets.model_builder.recipe import portable_recipe
    assert "references" not in portable_recipe(frozen["recipe"])[0]
    receipt = c.host.register_imported_asset(c.principal, c.scope.site_id, c.scope.layout_id,
                                             summary["draftId"])
    assert receipt["assetId"].startswith("asset-built-")
    provenance = json.loads((store._folder(c.scope) / "provenance" / (summary["draftId"] + ".json")).read_bytes())
    assert provenance == [{"referenceId": identifier, "kind": "image", "sha256":
                           store._record(c.scope, identifier)["sourceSha256"], "page": 0}]
    assert store._record(c.scope, identifier)["pins"] == []


def test_sage_inspects_reference_and_revises_with_comparison(references):
    from tests.test_model_builder_sage_tools import gateway
    c, store = references
    identifier, _ = upload(store, c.scope, png())
    read = gateway(c, edit=False)
    listed = asyncio.run(read.call("inspect_reference_file", {}))
    assert listed["ok"] and listed["data"]["references"][0]["referenceId"] == identifier
    viewed = asyncio.run(read.call("inspect_reference_file", {"referenceId": identifier}))
    assert viewed["ok"] and viewed["data"]["untrustedData"] is True
    assert read.take_image()["mimeType"] == "image/png"
    edit = gateway(c)
    built = asyncio.run(edit.call("build_model_draft", recipe()))
    assert built["ok"], built
    revised = asyncio.run(edit.call("revise_model_draft", {"draftId": built["data"]["draftId"],
        "edits": [{"op": "top", "set": {"name": "Revised equipment", "references": [identifier]}}],
        "compareWith": {"referenceId": identifier}}))
    assert revised["ok"], revised
    assert store.draft_references(c.scope, revised["data"]["draftId"]) == [identifier]
    assert edit.take_image()["mimeType"] == "image/png"


def test_identical_model_draft_keeps_both_site_references(references):
    c, store = references
    first_id, _ = upload(store, c.scope, png())
    second_id, _ = upload(store, c.scope, png(metadata=True))
    plain, _ = c.host.build_model_draft(c.principal, c.reference, recipe())
    first, _ = c.host.build_model_draft(c.principal, c.reference, recipe(references=[first_id]))
    second, _ = c.host.build_model_draft(c.principal, c.reference, recipe(references=[second_id]))
    assert plain["draftId"] == first["draftId"] == second["draftId"]
    assert store.draft_references(c.scope, first["draftId"]) == [first_id, second_id]
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
    restarted = LocalFacilityLayoutHost(c.host.root, private_assets=True,
                                        private_asset_root=c.host._component_visual_root)
    try:
        restarted.ensure_bootstrap()
        restarted.register_imported_asset(c.principal, c.scope.site_id, c.scope.layout_id, first["draftId"])
    finally:
        restarted.close()
    provenance = json.loads((store._folder(c.scope) / "provenance" / (first["draftId"] + ".json")).read_bytes())
    assert [row["referenceId"] for row in provenance] == [first_id, second_id]
    third_id, _ = upload(store, c.scope, png())
    third, _ = c.host.build_model_draft(c.principal, c.reference, recipe(references=[third_id]))
    assert third["draftId"] == first["draftId"]
    c.host.register_imported_asset(c.principal, c.scope.site_id, c.scope.layout_id, third["draftId"])
    provenance = json.loads((store._folder(c.scope) / "provenance" / (third["draftId"] + ".json")).read_bytes())
    assert [row["referenceId"] for row in provenance] == [first_id, second_id, third_id]
    assert store._record(c.scope, third_id)["pins"] == []
    fourth_id, _ = upload(store, c.scope, png())
    with pytest.raises(FacilityLayoutError) as caught:
        c.host.build_model_draft(c.principal, c.reference, recipe(references=[fourth_id]))
    assert caught.value.code == "reference_limit"
    assert store._record(c.scope, fourth_id)["pins"] == []


def test_worker_refuses_oversized_declared_pixels_without_decoding(tmp_path):
    import struct
    import zlib
    raw = bytearray(png())
    raw[16:24] = struct.pack(">II", 10000, 10000)
    raw[29:33] = struct.pack(">I", zlib.crc32(raw[12:29]) & 0xffffffff)
    job = tmp_path / "job"
    job.mkdir()
    (job / "source.bin").write_bytes(raw)
    (job / "request.json").write_bytes(b'{"pdf":false}')
    with pytest.raises(ModelBuildError) as caught:
        run_reference(job, model_import_runtime().dependency_root)
    assert caught.value.code in {"reference_limit", "reference_invalid"}


@pytest.mark.skipif(importlib.util.find_spec("fitz") is None, reason="PyMuPDF is unavailable in this test venv")
def test_opt_in_pdf_encryption_and_worker_timeout(context):
    import fitz
    c = context
    store = ReferenceStore(c.host.service, reference_pdf=True,
                           dependency_root=model_import_runtime().dependency_root)
    c.host.service._reference_store = store
    doc = fitz.open()
    doc.new_page()
    encrypted = doc.tobytes(encryption=fitz.PDF_ENCRYPT_AES_256, owner_pw="owner", user_pw="user")
    _, failed = upload(store, c.scope, encrypted, "sheet.pdf")
    assert failed["state"] == "failed" and failed["refusal"]["code"] == "reference_invalid"
    plain = doc.tobytes()
    identifier, ready = upload(store, c.scope, plain, "sheet.pdf")
    assert ready["state"] == "ready" and ready["kind"] == "pdf"
    assert store.page(c.scope, identifier, 0)[0].startswith(b"\x89PNG")
    many = fitz.open()
    for index in range(21):
        page = many.new_page()
        if index == 0:
            page.insert_text((40, 40), "Reference measurement")
    many_id, many_record = upload(store, c.scope, many.tobytes(), "many.pdf")
    assert many_record["state"] == "ready" and many_record["pages"] == 21
    assert "Reference measurement" in store.page(c.scope, many_id, 0)[1]["text"]
    with pytest.raises(FacilityLayoutError):
        store.page(c.scope, many_id, 20)
    job = Path(c.host.root) / "timeout-reference"
    job.mkdir()
    (job / "source.bin").write_bytes(plain)
    (job / "request.json").write_bytes(b'{"pdf":true}')
    from ai_inspector.industrial_assets.model_builder.imports import module
    with pytest.raises(module("errors").ModelImportError) as caught:
        run_reference(job, model_import_runtime().dependency_root, pdf=True, timeout=.001)
    assert caught.value.code == "model_timeout"
    import threading
    cancelled = threading.Event()
    timer = threading.Timer(.01, cancelled.set)
    timer.start()
    try:
        with pytest.raises(module("errors").ModelImportError) as caught:
            run_reference(job, model_import_runtime().dependency_root, pdf=True, cancel_event=cancelled)
        assert caught.value.code == "model_cancelled"
    finally:
        timer.cancel()


def test_pdf_missing_trusted_dependency_refuses_clearly(tmp_path):
    job = tmp_path / "job"
    job.mkdir()
    (job / "source.bin").write_bytes(b"%PDF-1.7\n")
    (job / "request.json").write_bytes(b'{"pdf":true}')
    dependencies = tmp_path / "empty-dependencies"
    dependencies.mkdir()
    with pytest.raises(ModelBuildError) as caught:
        run_reference(job, dependencies, pdf=True)
    assert caught.value.code == "reference_pdf_unavailable"


def test_streamed_routes_keep_scope_and_page_bytes(references):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_inspector.facility_layout.reference_file_routes import create_reference_file_router
    c, store = references
    app = FastAPI()
    app.include_router(create_reference_file_router(service=c.host.service, principal_resolver=lambda _: c.principal,
                                                    store=store))
    root = f"/api/facility-layouts/{c.scope.site_id}/{c.scope.layout_id}/reference-files"
    with TestClient(app) as client:
        response = client.post(root, content=png(), headers={"x-reference-name": "camera.jpg"})
        assert response.status_code == 202, response.text
        identifier = response.json()["referenceId"]
        for _ in range(200):
            record = client.get(root + "/" + identifier)
            if record.json().get("state") == "ready":
                break
            time.sleep(.05)
        assert record.status_code == 200 and record.json()["state"] == "ready"
        picture = client.get(root + "/" + identifier + "/pages/0")
        assert picture.status_code == 200 and picture.headers["content-type"] == "image/png"
        assert picture.content.startswith(b"\x89PNG")
        assert client.get(root + "/" + identifier + "/pages/1").status_code == 404
        assert client.get(root.replace(c.scope.site_id, "other-site") + "/" + identifier).status_code in (403, 404)


def photo_like(width=2600, height=1950, noise=6, seed=7):
    """A synthetic phone-style photo: smooth scene, fine texture and sensor noise, saved as JPEG."""
    import numpy as np
    rng = np.random.default_rng(seed)
    base = Image.fromarray(rng.integers(40, 220, (12, 16, 3), dtype=np.uint8)).resize((width, height), Image.BICUBIC)
    texture = Image.fromarray(rng.integers(0, 255, (height // 8, width // 8, 3), dtype=np.uint8)).resize(
        (width, height), Image.BILINEAR)
    pixels = (np.asarray(base, float) * .85 + np.asarray(texture, float) * .15
              + rng.normal(0, noise, (height, width, 3)))
    output = BytesIO()
    Image.fromarray(np.clip(pixels, 0, 255).astype(np.uint8)).save(output, "JPEG", quality=90)
    return output.getvalue()


def test_a_phone_sized_photo_is_stored_within_its_page_limit_and_sage_can_see_it(references):
    # This 1.3 MB JPEG made a 5.8 MB PNG at 2048 px (RGBA), over the 4 MB page limit, so photos were refused;
    # and any stored page over 1.5 MB could not be returned to Sage as a tool picture.
    from ai_inspector.codex_runtime.model_import_tools import PICTURE_BYTES
    from ai_inspector.facility_layout.reference_files import SAGE_PICTURE_BYTES
    from ai_inspector.industrial_assets.model_builder.reference_worker import MAX_PAGE_BYTES
    from tests.test_model_builder_sage_tools import gateway
    assert SAGE_PICTURE_BYTES == PICTURE_BYTES
    c, store = references
    identifier, row = upload(store, c.scope, photo_like())
    assert row["state"] == "ready", row
    stored, _ = store.page(c.scope, identifier)
    assert len(stored) <= MAX_PAGE_BYTES and stored[25] == 2  # PNG colour type 2: RGB, no needless alpha
    read = gateway(c, edit=False)
    viewed = asyncio.run(read.call("inspect_reference_file", {"referenceId": identifier}))
    assert viewed["ok"], viewed
    picture = base64.b64decode(read.take_image()["data"])
    assert len(picture) <= PICTURE_BYTES < len(stored), (len(picture), len(stored))
    with Image.open(BytesIO(picture)) as shown:
        assert max(shown.size) >= 900 and shown.size == (viewed["data"]["shownWidth"], viewed["data"]["shownHeight"])


def test_sweep_drops_page_choices_of_drafts_that_no_longer_exist(references):
    c, store = references
    identifier, _ = upload(store, c.scope, png())
    pages = store._folder(c.scope) / "draft-pages"
    pages.mkdir(parents=True, exist_ok=True)
    stale = pages / ("md-" + "0" * 24 + ".json")
    stale.write_text(json.dumps({identifier: 0}), encoding="utf-8")
    store.sweep()
    assert not stale.exists() and store.get(c.scope, identifier)["state"] == "ready"
