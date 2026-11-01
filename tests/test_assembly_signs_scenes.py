"""Safety signs, logos and scenes on assemblies (docs/assembly-signs-scenes-plan.md, AD1 and AD3): stored with the
assembly's appearance, sharing its revision, set through routes for the Assembly tab's panel and by Sage's tools.
No credentials or inference."""
from __future__ import annotations

import hashlib
from io import BytesIO
import json

from fastapi.testclient import TestClient
from PIL import Image
import pytest

import server
from ai_inspector.assembly_knowledge.assembly_appearance import (
    AssemblyAppearanceError, AssemblyAppearanceStore, finish, revision, sign,
)
from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway
from ai_inspector.codex_runtime.progress import describe
from tests.test_codex_assembly_appearance_tools import PARTS, AppearanceHost
from tests.test_codex_documentation_tools import PRINCIPAL, call

ENGINE = "100001"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ASSEMBLY_APPEARANCE_ROOT", tmp_path / "appearances")
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "sheets")
    return TestClient(server.app)


def test_a_sign_is_a_library_sign_or_an_imported_image_on_one_side_of_one_part():
    row = sign({"decalId": "iso7010-w024", "part": "door", "side": "front"}, parts={"door"}, images={})
    assert row["label"] == "Crushing of hands" and row["widthMeters"] == 0.3
    assert (row["across"], row["up"], row["rotationDegrees"]) == (0.5, 0.5, 0) and row["signId"].startswith("sg-")
    fire = sign({"decalId": "iso7010-w021", "part": "door", "side": "top", "across": 0.2, "widthMeters": 0.12},
                parts={"door"}, images={})
    assert fire["label"] == "Flammable material" and fire["across"] == 0.2 and fire["widthMeters"] == 0.12
    pinned = sign({"decalId": "iso7010-p010", "part": "door", "anchor": {"mesh": 1, "point": [0, 1, 2],
                   "normal": [0, 0, 1]}}, parts={"door"}, images={})
    assert pinned["anchor"] == {"mesh": 1, "point": [0, 1, 2], "normal": [0, 0, 1]}
    logo = sign({"imageId": "a" * 64, "part": "door"}, parts={"door"}, images={"a" * 64: {"label": "Our logo"}})
    assert logo["label"] == "Our logo" and "decalId" not in logo
    for bad, message in (
            ({"decalId": "iso7010-w999", "part": "door"}, "not a sign in the library"),
            ({"decalId": "iso7010-w024", "imageId": "a" * 64, "part": "door"}, "needs a decalId"),
            ({"decalId": "iso7010-w024", "part": "spindle"}, "not a part"),
            ({"decalId": "iso7010-w024", "part": "door", "side": "inside"}, "side must be one of"),
            ({"decalId": "iso7010-w024", "part": "door", "across": 1.5}, "across must be a number from 0 to 1"),
            ({"decalId": "iso7010-w024", "part": "door", "widthMeters": 9}, "widthMeters"),
            ({"imageId": "b" * 64, "part": "door"}, "not an image imported"),
            ({"decalId": "iso7010-w024", "part": "door", "anchor": {"point": [0, 0, 0], "normal": [0, 0, 0]}},
             "normal must not be zero")):
        with pytest.raises(AssemblyAppearanceError, match=message):
            sign(bad, parts={"door"}, images={"a" * 64: {}})


def test_scenes_and_signs_share_the_revision_and_an_assembly_with_finishes_only_keeps_its_own(tmp_path):
    store = AssemblyAppearanceStore(tmp_path)
    parts = {"door", "frame"}
    document = store.write("asset-x", {"appearanceId": "paint-machine-gray"}, {}, part_numbers=parts, by="sage")
    before = hashlib.sha256(json.dumps({"whole": document["whole"], "parts": {}}, sort_keys=True,
                                       separators=(",", ":")).encode("utf-8")).hexdigest()[:16]
    assert revision(document) == before
    lit = store.set_scene("asset-x", "machine-shop", by="sage")
    assert lit["scene"] == {"sceneId": "machine-shop"} and revision(lit) not in ("", before)
    with pytest.raises(AssemblyAppearanceError, match="not a scene"):
        store.set_scene("asset-x", "moon-base", by="sage")
    signed = store.set_signs("asset-x", [{"decalId": "iso7010-w024", "part": "door", "side": "left"}],
                             part_numbers=parts, by="sage")
    assert revision(signed) not in (revision(lit), before)
    # Changing the finishes keeps the scene and the signs.
    kept = store.write("asset-x", None, {"frame": finish({"appearanceId": "steel-brushed"})}, part_numbers=parts,
                       by="sage")
    assert kept["scene"] == {"sceneId": "machine-shop"} and len(kept["signs"]) == 1
    with pytest.raises(AssemblyAppearanceError, match="its own signId"):
        store.set_signs("asset-x", [signed["signs"][0], signed["signs"][0]], part_numbers=parts, by="sage")
    assert store.set_scene("asset-x", "classic", by="sage")["scene"] is None
    # An imported logo alone changes nothing a capture shows; clearing keeps it for later.
    image = store.add_image("asset-y", b"png-bytes", label="Logo", width=200, height=100, by="workspace")
    assert image["aspect"] == 2.0 and revision(store.read("asset-y")) == ""
    store.set_signs("asset-y", [{"imageId": image["imageId"], "part": "door"}], part_numbers=parts, by="sage")
    cleared = store.clear("asset-y", by="workspace")
    assert cleared["signs"] == [] and list(cleared["images"]) == [image["imageId"]] and revision(cleared) == ""


def _png_with_margin():
    picture = Image.new("RGBA", (200, 100), (0, 0, 0, 0))
    picture.paste((200, 30, 30, 255), (50, 25, 150, 75))
    output = BytesIO()
    picture.save(output, format="PNG")
    return output.getvalue()


def test_the_routes_set_the_scene_and_signs_import_a_logo_and_record_what_the_viewer_measured(client):
    part = next(iter(server._assembly_appearance_parts(ENGINE)))
    lit = client.put(f"/api/assembly-appearance/{ENGINE}/scene", json={"sceneId": "machine-shop"}).json()
    assert lit["scene"]["sceneId"] == "machine-shop" and lit["scene"]["environmentUrl"].endswith(".hdr")
    assert client.put(f"/api/assembly-appearance/{ENGINE}/scene", json={"sceneId": "moon"}).status_code == 400
    imported = client.post(f"/api/assembly-appearance/{ENGINE}/images?label=Acme", content=_png_with_margin())
    image = imported.json()["image"]
    assert imported.status_code == 200 and image["label"] == "Acme"
    # Cut to the visible pixels (with the importer's 2-pixel border): about twice as wide as high.
    assert image["width"] < 120 and 1.8 < image["aspect"] < 2.0
    served = client.get(image["url"])
    assert served.status_code == 200 and served.headers["content-type"] == "image/png"
    assert client.get("/api/assembly-appearance-images/../x.png").status_code == 404
    assert client.post(f"/api/assembly-appearance/{ENGINE}/images", content=b"not an image").status_code == 400
    signed = client.put(f"/api/assembly-appearance/{ENGINE}/signs", json={"signs": [
        {"decalId": "iso7010-w017", "part": part, "side": "top"},
        {"imageId": image["imageId"], "part": part, "side": "front", "widthMeters": 0.2}]}).json()
    hot, logo = signed["signs"]
    assert hot["url"].endswith("decals/iso7010-w017.svg") and hot["code"] == "ISO 7010 W017"
    assert logo["url"] == image["url"] and logo["aspect"] == image["aspect"] and signed["revision"]
    assert client.put(f"/api/assembly-appearance/{ENGINE}/signs", json={"signs": [
        {"decalId": "iso7010-w017", "part": "no-such-part"}]}).status_code == 400
    measured = client.put(f"/api/assembly-appearance/{ENGINE}/geometry", json={
        "parts": {part: {"center": [0, 0.5, 0], "size": [0.4, 0.3, 0.2]}, "unknown": {"center": [0, 0, 0],
                  "size": [1, 1, 1]}},
        "bounds": {"min": [-1, 0, -1], "max": [1, 2, 1]},
        "signs": {hot["signId"]: {"status": "placed", "widthMeters": 0.3}, logo["signId"]: {"status": "no_surface"}},
        "revision": signed["revision"]})
    assert measured.json() == {"success": True, "parts": 1, "signs": 2}
    stored = server._assembly_appearance_store().read_geometry(ENGINE)
    assert stored["signs"][logo["signId"]] == {"status": "no_surface"} and list(stored["parts"]) == [part]
    sheet = client.get(f"/api/specification-sheet/{ENGINE}/documentation-scene")
    if sheet.status_code == 200:
        assert sheet.json()["document"]["pages"][0]["renderRequest"]["appearanceRevision"] == signed["revision"]
    reset = client.delete(f"/api/assembly-appearance/{ENGINE}").json()
    assert reset["signs"] == [] and reset["scene"] is None and [row["imageId"] for row in reset["images"]] == [
        image["imageId"]]


class SignHost(AppearanceHost):
    """The documentation host with signs, scenes and what the viewer measured, as _DocumentationAgentHost has them."""

    def assembly_geometry(self, number):
        return self.store.read_geometry(number)

    def write_assembly_scene(self, number, scene_id):
        return self.store.set_scene(number, scene_id, by="sage")

    def write_assembly_signs(self, number, signs):
        return self.store.set_signs(number, signs, part_numbers=PARTS, by="sage")


def test_sage_reads_where_parts_sit_places_signs_shrunk_to_fit_sets_the_scene_and_removes_signs(tmp_path):
    host = SignHost(tmp_path)
    host.store.write_geometry("tricycle", {"parts": {"door": {"center": [0, 0.5, 0.41], "size": [0.2, 0.3, 0.02]}},
                                           "bounds": {"min": [-1, 0, -1], "max": [1, 2, 1]}}, part_numbers=PARTS)
    gateway = DocumentationGateway(host, PRINCIPAL, {"assemblyNumber": "tricycle", "documentType": None},
                                   turn_id="turn", workspace="assembly", max_calls=30)
    parts = call(gateway, "list_appearances", {})["data"]
    assert parts["parts"][1] == {"part": "door", "name": "Door", "center": [0, 0.5, 0.41], "size": [0.2, 0.3, 0.02]}
    assert "front faces +Z" in parts["axes"] and parts["machineBounds"]["max"] == [1, 2, 1]
    listed = call(gateway, "list_signs_and_scenes", {"query": "crush"})["data"]
    assert {row["label"] for row in listed["signs"]} == {"Crushing", "Crushing of hands"}
    assert "machine-shop" in {row["sceneId"] for row in listed["scenes"]} and listed["now"] == {
        "scene": "classic", "signs": []}
    assert "check the site's rules" in listed["note"]
    placed = call(gateway, "place_assembly_signs", {"signs": [
        {"sign": "iso7010-w024", "part": "door", "side": "front"},
        {"sign": "iso7010-w021", "part": "frame", "side": "left", "widthMeters": 0.1}]})
    assert placed["ok"], placed
    pinch, fire = placed["data"]["placed"]
    # The door's front is 0.2 m wide: the 0.3 m sign is shrunk to nine tenths of it. The frame is not measured.
    assert pinch["widthMeters"] == 0.18 and "shrunk to 0.18 m" in placed["data"]["fitted"][0]
    assert fire == {"signId": fire["signId"], "label": "Flammable material", "part": "frame", "side": "left",
                    "widthMeters": 0.1}
    assert call(gateway, "place_assembly_signs", {"signs": [{"sign": "iso7010-w024", "part": "wheel",
                                                             "side": "front"}]})["error"]["code"] == "sign_unknown_part"
    assert call(gateway, "place_assembly_signs", {"signs": [{"sign": "iso7010-w999", "part": "door",
                                                             "side": "front"}]})["error"]["code"] == "sign_unknown"
    assert call(gateway, "set_assembly_scene", {"sceneId": "machine-shop"})["data"]["scene"] == "machine-shop"
    assert call(gateway, "set_assembly_scene", {"sceneId": "moon-base"})["error"]["code"] == "scene_invalid"
    now = call(gateway, "list_signs_and_scenes", {})["data"]["now"]
    assert now["scene"] == "machine-shop" and [row["shown"] for row in now["signs"]] == ["not drawn yet"] * 2
    removed = call(gateway, "remove_assembly_signs", {"signIds": [pinch["signId"]]})["data"]
    assert removed["removed"] == 1 and removed["signCount"] == 1
    assert call(gateway, "remove_assembly_signs", {"signIds": ["sg-0000000000"]})["error"]["code"] == "sign_unknown"
    assert gateway.appearance_changes == ["tricycle"]
    gateway.queued.append({"name": "open_library_machine", "args": {"asset_id": "asset-x", "view": "assembly"}})
    assert call(gateway, "place_assembly_signs", {"signs": [{"sign": "iso7010-w024", "part": "door",
                                                             "side": "front"}]})["error"]["code"] \
        == "appearance_machine_opening"
    assert describe("place_assembly_signs", {"signs": [{}, {}]})["done"] == "Placed 2 signs on the machine"
    assert describe("remove_assembly_signs", {"all": True})["done"] == "Removed the machine's signs"
    assert describe("set_assembly_scene", {})["running"] == "Updating the machine's lighting scene"


def test_a_report_without_parts_keeps_what_was_measured_and_the_viewer_reads_where_signs_landed(client):
    part = next(iter(server._assembly_appearance_parts(ENGINE)))
    url = f"/api/assembly-appearance/{ENGINE}"
    signed = client.put(url + "/signs", json={"signs": [{"decalId": "iso7010-w024", "part": part}]}).json()
    sign_id = signed["signs"][0]["signId"]
    client.put(url + "/geometry", json={"parts": {part: {"center": [0, 1, 0], "size": [1, 1, 1]}},
                                        "bounds": {"min": [0, 0, 0], "max": [1, 2, 1]}, "signs": {}})
    # Exploded or moving: only where the signs landed.
    client.put(url + "/geometry", json={"signs": {sign_id: {"status": "no_surface"}}})
    stored = server._assembly_appearance_store().read_geometry(ENGINE)
    assert stored["parts"][part]["center"] == [0, 1, 0] and stored["bounds"]["max"] == [1, 2, 1]
    assert client.get(url).json()["signStatus"] == {sign_id: "no_surface"}
    # A sign with no flat, uncovered spot even at 3 cm is not drawn; the view says so (no_fit).
    client.put(url + "/geometry", json={"signs": {sign_id: {"status": "no_fit"}}})
    assert client.get(url).json()["signStatus"] == {sign_id: "no_fit"}


def test_the_assembly_view_draws_scenes_and_signs_and_the_assembly_tab_has_its_library_panel():
    html = (server.Path(server.__file__).parent / "static" / "index.html").read_text("utf-8")
    for needle in (
            'src="/static/vendor/three/0.128.0/examples/js/geometries/DecalGeometry.js"',
            'src="/static/vendor/three/0.128.0/examples/js/loaders/RGBELoader.js"',
            'src="/static/assembly_library_panel.js?v=',
            'id="assemblyLibraryPanelHost" hidden',
            "const FACILITY_LIBRARY_VERSION = '2026.11.01.1';",
            # One refresh at a time; it resolves once the scene and signs are drawn, which the capture awaits.
            "state._assyAppearanceChain = (state._assyAppearanceChain || Promise.resolve()).then(run, run);",
            "if (state.assyScene && redraw) await _assemblySceneApply(state.assyFinish.scene);",
            "await _assemblySignsRebuild();",
            # r128 lights are the library's r184 levels over pi; Classic brings the view's own back.
            "lights.ambient.intensity = Math.max(0, Number(scene.ambient) || 0) / Math.PI;",
            "if (s.userData && s.userData._assemblySceneBackground) return;",
            # Signs follow their part, show only in shaded styles, and stay out of line art.
            "if (scene === state.assyScene && !_cadIsPart()) _assemblySignsSync();",
            ": style === 'shaded' || style === 'shaded_edges';",
            "|| object.userData?._assemblySign",
            "shaded: illustrationStyle === PARTS_MANUAL_ILLUSTRATION_STYLE.SHADED_COLOR,",
            "mesh.raycast = () => {};",
            # The geometry report goes to the view it measured: the Assembly view's or the part's (3D Model tab).
            "fetch(_cadAppearanceUrl(number, '/geometry'), {",
            "return `/api/assembly-appearance/${encodeURIComponent(number)}${tail || ''}`;",
            # The library icon opens the Assembly pane in the Assembly tab.
            "if (assemblyTab) return _mountAssemblyLibraryPanel();",
            "if (redraw && _assemblyLibraryPanelInstance) _assemblyLibraryPanelInstance.refresh();",
    ):
        assert needle in html, needle
    start = html.index("// ===== Assembly scenes and signs")
    end = html.index("function applyPartHighlight3D()")
    assert html[start:end].isascii()
    panel_start = html.index("// ---- The Assembly tab's library pane")
    assert html[panel_start:html.index("function _trainBindLibraryPanel(appInstance) {")].isascii()
