"""Appearances on assemblies (docs/assembly-appearance-plan.md, AP1): finishes from the appearance library on the
whole machine or its parts, stored per assembly, served resolved for the viewer, and making the spec sheet's
product picture stale when they change. No credentials or inference."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.assembly_knowledge.assembly_appearance import (
    AssemblyAppearanceError, AssemblyAppearanceStore, finish, resolved, revision,
)

ENGINE = "100001"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ASSEMBLY_APPEARANCE_ROOT", tmp_path / "appearances")
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "sheets")
    return TestClient(server.app)


def test_a_finish_is_a_library_appearance_with_the_overrides_the_viewer_draws():
    assert finish({"appearanceId": "paint-gloss-red", "color": "#1D4F91", "textureStrength": 0.5}) == {
        "appearanceId": "paint-gloss-red", "color": "#1d4f91"}
    with pytest.raises(AssemblyAppearanceError, match="not in the appearance library"):
        finish({"appearanceId": "gold-leaf"})
    with pytest.raises(AssemblyAppearanceError, match="six-digit hex"):
        finish({"appearanceId": "paint-gloss-red", "color": "blue"})
    glass = resolved({"appearanceId": "glass-clear"})
    assert glass["opacity"] < 0.4 and glass["metalness"] == 0
    assert resolved({"appearanceId": "steel-brushed"})["textured"] is True


def test_the_store_assigns_and_clears_and_its_revision_is_empty_without_finishes(tmp_path):
    store = AssemblyAppearanceStore(tmp_path)
    parts = {"door", "frame"}
    assert revision(store.read("asset-x")) == ""
    store.assign("asset-x", finish_value=finish({"appearanceId": "paint-machine-gray"}), whole=True,
                 part_numbers=parts, by="sage")
    document = store.assign("asset-x", finish_value=finish({"appearanceId": "glass-clear"}), parts=["door"],
                            part_numbers=parts, by="sage")
    assert document["whole"]["appearanceId"] == "paint-machine-gray" and list(document["parts"]) == ["door"]
    first = revision(store.read("asset-x"))
    assert first and first == revision(document)
    with pytest.raises(AssemblyAppearanceError, match="not parts of asset-x: spindle"):
        store.assign("asset-x", finish_value=finish({"appearanceId": "steel-brushed"}), parts=["spindle"],
                     part_numbers=parts, by="sage")
    store.assign("asset-x", finish_value=None, parts=["door"], part_numbers=parts, by="sage")
    assert revision(store.read("asset-x")) not in ("", first)
    store.assign("asset-x", finish_value=None, whole=True, part_numbers=parts, by="sage")
    assert revision(store.read("asset-x")) == "" and not (tmp_path / "asset-x.json").exists()
    with pytest.raises(AssemblyAppearanceError):
        store.read("../escape")


def test_the_routes_set_read_and_clear_an_assemblys_finishes(client):
    parts = server._assembly_appearance_parts(ENGINE)
    part = sorted(parts)[0]
    assert client.get(f"/api/assembly-appearance/{ENGINE}").json()["revision"] == ""
    put = client.put(f"/api/assembly-appearance/{ENGINE}", json={
        "whole": {"appearanceId": "paint-powder-blue"}, "parts": {part: {"appearanceId": "steel-polished"}}})
    assert put.status_code == 200, put.json()
    shown = client.get(f"/api/assembly-appearance/{ENGINE}").json()
    assert shown["revision"] and shown["whole"]["label"] and shown["parts"][part]["metalness"] == 1
    refused = client.put(f"/api/assembly-appearance/{ENGINE}", json={"parts": {"not-a-part": {
        "appearanceId": "steel-polished"}}})
    assert refused.status_code == 400 and "not-a-part" in refused.json()["message"]
    assert client.put("/api/assembly-appearance/no-such-assembly", json={}).status_code == 404
    assert client.delete(f"/api/assembly-appearance/{ENGINE}").json()["revision"] == ""


def test_a_new_appearance_makes_the_spec_sheet_picture_stale_and_none_keeps_it(client):
    def document():
        return client.get(f"/api/specification-sheet/{ENGINE}/documentation-scene").json()["document"]

    client.post(f"/api/specification-sheet/{ENGINE}/generate?rebaseline=true")
    before = document()
    assert "appearanceRevision" not in before["pages"][0]["renderRequest"]
    client.put(f"/api/assembly-appearance/{ENGINE}", json={"whole": {"appearanceId": "paint-safety-yellow"}})
    painted = document()
    assert painted["pages"][0]["renderRequest"]["appearanceRevision"]
    assert painted["figureRevision"] != before["figureRevision"]
    client.delete(f"/api/assembly-appearance/{ENGINE}")
    assert document()["figureRevision"] == before["figureRevision"]


def test_the_page_draws_the_finishes_with_each_scene_before_each_capture_and_after_sage():
    page = (server.REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8-sig")
    stream = (server.REPO_ROOT / "static" / "chat_stream_runtime.js").read_text(encoding="utf-8")
    base = page[page.index("function _applyAssemblyMeshBaseMaterial("):page.index("function applyPartHighlight3D()")]
    assert "_assemblyFinishForMesh(mesh)" in base
    # A face's own finish wins over the part's (docs/assembly-face-selection-plan.md).
    assert "_applyAssemblyFinish(mat, mat.userData?._assemblyFaceFinish || finish)" in base
    assert ".convertSRGBToLinear()" in page and "0.15 + 0.85 * material.metalness" in page
    mesh_map = page[page.index("function _buildPartMeshMap("):page.index("// ===== Exploded View Functions")]
    assert "void _assemblyAppearanceRefresh({ reapply: true });" in mesh_map
    capture = page[page.index("async function _partsManualCaptureAndStorePage("):][:2500]
    assert capture.index("await _assemblyAppearanceRefresh();") < capture.index("_partsManualViewDocumentPage(")
    assert "(sheetWork.appearanceChanges || []).length" in page
    assert "status?.assemblyRuntime === 'codex'" in page and "activeMode === 'assembly'" in page
    assert "codex_assembly: 'Reading the assembly'" in stream
    assert "chat_stream_runtime.js?v=20261028-part-2" in page


def test_a_queued_publish_loads_a_blank_sheet_and_keeps_the_requested_product_view():
    page = (server.REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8-sig")
    publish = page[page.index("publish_specification_sheet: {"):][:2600]
    # The workspace opens blank (no pages) until Refresh: a queued publish loads the saved sheet before capturing.
    assert publish.index("await _documentationReloadWorkflow();") \
        < publish.index("await _documentationGenerateSpecificationSheetBaseline(")
    assert "(model.pages || []).some(page => page.renderRequest)" in publish
    # The isometric product view is kept when it fills the minimum, or as large as the frame allows for a long
    # machine (a robot arm), not swapped for a flat side view.
    assert ("const keepsRequested = candidate.name === requestedCameraPreset && (reachesMinimum\n"
            "                            || imageRequest.axisConstrainedOccupancyPolicy\n"
            "                                === 'allow_when_uniform_scale_exceeds_axis_limit');") in page
    assert "const score = (keepsRequested ? 3000 : 0)" in page


def test_the_capture_holds_its_camera_while_it_waits_and_long_machines_fill_the_width(client):
    page = (server.REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8-sig")
    stage = page[page.index("const markCaptureStage = async name => {"):][:1600]
    # A view moved by hand keeps the orbit control re-placing the camera on every frame (the ABB robot's capture
    # framed the user's angle and stopped): the orbit is synced to the capture camera before each wait.
    assert stage.index("_syncOrbitFromCamera(state.assyControls, state.assyCamera);") \
        < stage.index("await new Promise(resolve => requestAnimationFrame(")
    client.post(f"/api/specification-sheet/{ENGINE}/generate?rebaseline=true")
    image = client.get(f"/api/specification-sheet/{ENGINE}/documentation-scene").json()[
        "document"]["pages"][0]["renderRequest"]["image"]
    assert image["axisConstrainedOccupancyPolicy"] == "allow_when_uniform_scale_exceeds_axis_limit"
    assert image["axisConstrainedFillTolerance"] == 0.02 and image["allowAutomaticCameraSelection"] is True
