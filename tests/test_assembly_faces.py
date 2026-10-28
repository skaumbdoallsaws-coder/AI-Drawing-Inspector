"""Faces of parts (docs/assembly-face-selection-plan.md, F2-F4): finishes on one face of a part kept with the
assembly's appearance and its revision, the faces the user selected and each part's largest faces as the 3D view
reported them, the routes the Assembly tab uses, and Sage's tools reading faces and putting finishes and signs on
them. No credentials or inference."""
from __future__ import annotations

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.assembly_knowledge.assembly_appearance import (
    AssemblyAppearanceError, AssemblyAppearanceStore, face_finish, face_key, revision,
)
from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway
from ai_inspector.codex_runtime.progress import describe
from tests.test_assembly_signs_scenes import ENGINE, SignHost
from tests.test_codex_assembly_appearance_tools import PARTS
from tests.test_codex_documentation_tools import PRINCIPAL, call

PRINT_TOP = {"area": 0.12, "center": [0, 0.5, 0], "normal": [0, 1, 0]}
PRINT_SIDE = {"area": 0.03, "center": [0.1, 0.25, 0], "normal": [1, 0, 0]}


def face_row(face, print_, **extra):
    return {"mesh": 0, "face": face, "fingerprint": print_, **extra}


def report_rows():
    return [face_row(3, PRINT_TOP, kind="plane", areaM2=0.12, center=[0, 1.1, 0.4], side="top",
                     feature="Boss-Extrude1"),
            face_row(5, PRINT_SIDE, kind="plane", areaM2=0.03, center=[0.1, 0.85, 0.4], side="right"),
            face_row(9, {"area": 0.004, "center": [0, 0, 0], "normal": [0, 0, 0.1]}, kind="cylinder",
                     areaM2=0.004, center=[0, 0.7, 0.4], radiusM=0.02)]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ASSEMBLY_APPEARANCE_ROOT", tmp_path / "appearances")
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "sheets")
    return TestClient(server.app)


def test_a_face_finish_names_a_part_a_face_and_its_fingerprint_and_joins_the_revision(tmp_path):
    row = face_finish({"part": "door", "face": 3, "fingerprint": PRINT_TOP,
                       "finish": {"appearanceId": "paint-safety-yellow"}}, parts=PARTS)
    assert row == {"part": "door", "mesh": 0, "face": 3, "fingerprint": PRINT_TOP,
                   "finish": {"appearanceId": "paint-safety-yellow"}}
    assert face_key(row) == "door#0:3"
    for bad, message in ((dict(row, part="wheel"), "not a part"), (dict(row, face=-1), "whole number"),
                         (dict(row, fingerprint={"area": 1, "center": [0, 0, 0], "normal": [0, 2, 0]}), "direction"),
                         (dict(row, fingerprint=None), "fingerprint"), (dict(row, finish={}), "finish")):
        with pytest.raises(AssemblyAppearanceError, match=message):
            face_finish(bad, parts=PARTS)
    store = AssemblyAppearanceStore(tmp_path)
    parts_only = store.write("tricycle", None, {"door": {"appearanceId": "paint-safety-orange"}}, part_numbers=PARTS,
                             by="test")
    before = revision(parts_only)
    assert "faces" not in parts_only or parts_only["faces"] == []
    painted = store.write("tricycle", None, parts_only["parts"], part_numbers=PARTS, by="test", faces=[row])
    assert revision(painted) != before and painted["faces"] == [row]
    assert store.write("tricycle", None, parts_only["parts"], part_numbers=PARTS, by="test")["faces"] == [row], \
        "finishes written without faces keep the face finishes"
    assert revision(store.write("tricycle", None, parts_only["parts"], part_numbers=PARTS, by="test",
                                faces=[])) == before, "an assembly whose face finishes come off is back where it was"
    with pytest.raises(AssemblyAppearanceError, match="listed twice"):
        store.write("tricycle", None, {}, part_numbers=PARTS, by="test", faces=[row, row])
    only_face = store.write("tricycle", None, {}, part_numbers=PARTS, by="test", faces=[row])
    assert store.read("tricycle")["faces"] == [row] and revision(only_face)


def test_the_view_reports_face_finishes_drawn_the_selection_kept_and_each_part_s_largest_faces(tmp_path):
    store = AssemblyAppearanceStore(tmp_path)
    report = {"parts": {"door": {"center": [0, 1, 0.4], "size": [0.2, 0.3, 0.02]}}, "signs": {},
              "faces": {"door#0:3": {"status": "drawn", "face": 3, "copies": 2},
                        "door#0:5": {"status": "face_missing"}, "x": {"status": "melted"}},
              "selection": [{"part": "door", **face_row(3, PRINT_TOP, kind="plane", areaM2=0.12, side="top",
                                                         center=[0, 1.1, 0.4])},
                            {"part": "wheel", **face_row(1, PRINT_TOP)}]}
    stored = store.write_geometry("tricycle", report, part_numbers=PARTS)
    assert stored["faces"] == {"door#0:3": {"status": "drawn", "face": 3, "copies": 2},
                               "door#0:5": {"status": "face_missing"}}
    assert [(row["part"], row["face"], row["side"]) for row in stored["selection"]] == [("door", 3, "top")]
    # Exploded or moving: no parts and no selection in the report; what the user selected stays.
    kept = store.write_geometry("tricycle", {"signs": {}}, part_numbers=PARTS)
    assert kept["selection"] == stored["selection"] and kept["parts"] == stored["parts"]
    assert store.write_geometry("tricycle", {"selection": []}, part_numbers=PARTS)["selection"] == []
    with pytest.raises(AssemblyAppearanceError, match="at most 50"):
        store.write_geometry("tricycle", {"selection": [{"part": "door", **face_row(1, PRINT_TOP)}] * 51},
                             part_numbers=PARTS)
    faces = store.write_face_report("tricycle", {"parts": {
        "door": {"faceCount": 64, "copies": 2, "faces": report_rows() + [face_row(k, PRINT_SIDE) for k in range(50)]},
        "spindle": {"faceCount": 3, "approximate": True, "faces": [face_row(0, PRINT_SIDE, approximate=True)]},
        "wheel": {"faces": report_rows()}}}, part_numbers=PARTS)
    door = store.read_face_report("tricycle")["parts"]["door"]
    assert set(faces["parts"]) == {"door", "spindle"} and len(door["faces"]) == 40
    assert door["faceCount"] == 64 and door["copies"] == 2
    assert door["faces"][0] == {"mesh": 0, "face": 3, "fingerprint": PRINT_TOP, "kind": "plane", "areaM2": 0.12,
                                "center": [0, 1.1, 0.4], "side": "top", "feature": "Boss-Extrude1"}
    assert door["faces"][2]["radiusM"] == 0.02 and "side" not in door["faces"][2]
    assert faces["parts"]["spindle"]["approximate"] and faces["parts"]["spindle"]["faces"][0]["kind"] == "other"
    with pytest.raises(AssemblyAppearanceError, match="face report"):
        store.write_face_report("tricycle", {"faces": []}, part_numbers=PARTS)


def test_the_routes_put_finishes_on_faces_say_which_were_drawn_and_take_the_view_s_faces(client):
    part = next(iter(server._assembly_appearance_parts(ENGINE)))
    url = f"/api/assembly-appearance/{ENGINE}"
    row = {"part": part, "mesh": 0, "face": 3, "fingerprint": PRINT_TOP, "finish": {"appearanceId": "paint-safety-yellow"}}
    put = client.put(url, json={"whole": None, "parts": {}, "faces": [row]})
    assert put.status_code == 200 and put.json()["assigned"]["faces"] == [row]
    assert put.json()["faces"][0]["finish"]["color"], "resolved for the viewer"
    assert client.put(url, json={"whole": None, "parts": {}}).json()["assigned"]["faces"] == [row], "faces kept"
    bad = client.put(url, json={"whole": None, "parts": {}, "faces": [dict(row, part="no-such-part")]})
    assert bad.status_code == 400 and "not a part" in bad.json()["message"]
    key = f"{part}#0:3"
    measured = client.put(url + "/geometry", json={"faces": {key: {"status": "drawn", "face": 3}},
                                                   "selection": [{"part": part, **face_row(3, PRINT_TOP)}]})
    assert measured.json() == {"success": True, "parts": 0, "signs": 0}
    shown = client.get(url).json()
    assert shown["faceStatus"] == {key: "drawn"} and shown["signStatus"] == {}
    stored = server._assembly_appearance_store().read_geometry(ENGINE)
    assert stored["selection"][0]["face"] == 3
    listed = client.put(url + "/faces", json={"parts": {part: {"faceCount": 12, "copies": 1, "faces": report_rows()}}})
    assert listed.json() == {"success": True, "parts": 1}
    assert server._assembly_appearance_store().read_face_report(ENGINE)["parts"][part]["faceCount"] == 12
    assert client.put(url + "/faces", json={"parts": {part: {"faces": [{"face": 1}]}}}).status_code == 400
    assert client.put("/api/assembly-appearance/999999999/faces", json={"parts": {}}).status_code == 404


class FaceHost(SignHost):
    """The documentation host with face finishes and the view's list of faces, as _DocumentationAgentHost has them."""

    def write_assembly_appearance(self, number, whole, parts, faces=None):
        extra = {} if faces is None else {"faces": faces}
        return self.store.write(number, whole, parts, part_numbers=PARTS, by="sage", **extra)

    def assembly_face_report(self, number):
        return self.store.read_face_report(number)


def face_gateway(tmp_path, *, selection=(), report=True):
    host = FaceHost(tmp_path)
    host.store.write_geometry("tricycle", {"parts": {"door": {"center": [0, 1, 0.4], "size": [0.2, 0.3, 0.02]}},
                                           "selection": list(selection)}, part_numbers=PARTS)
    if report:
        host.store.write_face_report("tricycle", {"parts": {"door": {"faceCount": 12, "copies": 2,
                                                                     "faces": report_rows()}}}, part_numbers=PARTS)
    return host, DocumentationGateway(host, PRINCIPAL, {"assemblyNumber": "tricycle", "documentType": None},
                                      turn_id="turn", workspace="assembly", max_calls=30)


def test_sage_reads_a_part_s_faces_and_the_user_s_selection(tmp_path):
    _host, gateway = face_gateway(tmp_path, report=False)
    nothing = call(gateway, "list_part_faces", {})["data"]
    assert nothing["selectedFaces"] == [] and "No face is selected" in nothing["note"]
    unmeasured = call(gateway, "list_part_faces", {"part": "door"})["data"]
    assert unmeasured["faces"] == [] and "has not measured" in unmeasured["note"]
    assert call(gateway, "list_part_faces", {"part": "wheel"})["error"]["code"] == "faces_unknown_part"
    _host, gateway = face_gateway(tmp_path / "b", selection=[{"part": "frame", **face_row(
        7, PRINT_SIDE, kind="cylinder", areaM2=0.0312345, side="front", center=[0.2, 0.5, 0.1])}])
    listed = call(gateway, "list_part_faces", {"part": "door"})["data"]
    assert [row["face"] for row in listed["faces"]] == [3, 5, 9] and listed["copies"] == 2
    assert listed["faces"][0] == {"mesh": 0, "face": 3, "kind": "plane", "areaM2": 0.12, "center": [0, 1.1, 0.4],
                                  "side": "top", "feature": "Boss-Extrude1"}, "no fingerprints for Sage"
    assert listed["selectedFaces"] == [{"part": "frame", "mesh": 0, "face": 7, "kind": "cylinder", "areaM2": 0.0312,
                                        "center": [0.2, 0.5, 0.1], "side": "front"}]
    assert [row["face"] for row in call(gateway, "list_part_faces", {"part": "door", "side": "right"})["data"][
        "faces"]] == [5]
    assert [row["face"] for row in call(gateway, "list_part_faces", {"part": "door", "kind": "cylinder"})["data"][
        "faces"]] == [9]
    assert [row["face"] for row in call(gateway, "list_part_faces", {"part": "door", "minAreaM2": 0.01})["data"][
        "faces"]] == [3, 5]
    inspected = call(gateway, "inspect_assembly", {})["data"]
    assert inspected["selectedFaces"][0]["face"] == 7 and "list_part_faces" in inspected["note"]
    assert describe("list_part_faces", {})["running"] == "Reading the part's faces"


def test_sage_puts_finishes_on_listed_or_selected_faces_and_takes_them_off(tmp_path):
    host, gateway = face_gateway(tmp_path, selection=[{"part": "frame", **face_row(7, PRINT_SIDE, side="front")}])
    painted = call(gateway, "set_assembly_appearance", {"assignments": [
        {"target": "parts", "parts": ["door"], "appearanceId": "paint-safety-orange"},
        {"target": "faces", "faces": [{"part": "door", "face": 3}], "appearanceId": "paint-safety-yellow"},
        {"target": "faces", "faces": [{"part": "door", "face": 5}, {"part": "frame", "mesh": 0, "face": 7}],
         "appearanceId": "paint-safety-yellow", "color": "#111111"}]})
    assert painted["ok"], painted
    assert painted["data"]["faces"] == [
        {"part": "door", "mesh": 0, "face": 3, "appearanceId": "paint-safety-yellow"},
        {"part": "door", "mesh": 0, "face": 5, "appearanceId": "paint-safety-yellow", "color": "#111111"},
        {"part": "frame", "mesh": 0, "face": 7, "appearanceId": "paint-safety-yellow", "color": "#111111"}]
    stored = host.store.read("tricycle")
    assert [row["fingerprint"] for row in stored["faces"]] == [PRINT_TOP, PRINT_SIDE, PRINT_SIDE], \
        "the fingerprint comes from the view's list or the user's selection"
    assert stored["parts"] == {"door": {"appearanceId": "paint-safety-orange"}}
    unknown = call(gateway, "set_assembly_appearance", {"assignments": [
        {"target": "faces", "faces": [{"part": "door", "face": 44}], "appearanceId": "paint-safety-yellow"}]})
    assert unknown["error"]["code"] == "face_unknown" and len(host.store.read("tricycle")["faces"]) == 3
    assert call(gateway, "set_assembly_appearance", {"assignments": [
        {"target": "faces", "faces": [{"part": "wheel", "face": 1}], "appearanceId": "paint-safety-yellow"}]})[
        "error"]["code"] == "appearance_unknown_parts"
    host.store.write_geometry("tricycle", {"faces": {"door#0:3": {"status": "drawn"},
                                                     "door#0:5": {"status": "face_missing"}}}, part_numbers=PARTS)
    finishes = call(gateway, "inspect_assembly", {})["data"]["finishes"]
    assert [row["shown"] for row in finishes["faces"]] == ["drawn", "face_missing", "not drawn yet"]
    removed = call(gateway, "set_assembly_appearance", {"assignments": [
        {"target": "faces", "faces": [{"part": "door", "face": 5}], "remove": True}]})["data"]
    assert [row["face"] for row in removed["faces"]] == [3, 7]
    assert call(gateway, "set_assembly_appearance", {"clear": True})["ok"]
    assert host.store.read("tricycle")["faces"] == [] and gateway.appearance_changes == ["tricycle"]


def test_sage_puts_a_sign_on_one_face_and_the_view_keeps_it_inside_that_face(tmp_path):
    host, gateway = face_gateway(tmp_path, selection=[{"part": "frame", **face_row(7, PRINT_SIDE, side="front")}])
    placed = call(gateway, "place_assembly_signs", {"signs": [
        {"sign": "iso7010-w024", "part": "door", "face": {"face": 5}},
        {"sign": "iso7010-w018", "part": "frame", "face": {"mesh": 0, "face": 7}, "widthMeters": 0.1},
        {"sign": "iso7010-w021", "part": "door", "side": "front"}]})
    assert placed["ok"], placed
    on_face, selected, by_side = placed["data"]["placed"]
    assert on_face["side"] == "right" and on_face["face"] == {"mesh": 0, "face": 5}
    assert on_face["widthMeters"] == 0.3, "the view sizes a sign on a face to the face itself"
    assert selected["side"] == "front" and selected["widthMeters"] == 0.1
    assert "face" not in by_side and by_side["widthMeters"] == 0.18, "a side sign still fits the part's side"
    stored = host.store.read("tricycle")["signs"]
    assert stored[0]["face"] == {"mesh": 0, "face": 5, "fingerprint": PRINT_SIDE}
    assert "face" not in stored[2]
    now = call(gateway, "list_signs_and_scenes", {})["data"]["now"]["signs"]
    assert now[0]["face"] == {"mesh": 0, "face": 5} and "face" not in now[2]
    assert call(gateway, "place_assembly_signs", {"signs": [{"sign": "iso7010-w024", "part": "door"}]})["error"][
        "code"] == "sign_side_required"
    assert call(gateway, "place_assembly_signs", {"signs": [{"sign": "iso7010-w024", "part": "door",
                                                             "face": {"face": 99}}]})["error"]["code"] == "face_unknown"
    host.store.write_geometry("tricycle", {"signs": {stored[0]["signId"]: {"status": "face_missing"}}},
                              part_numbers=PARTS)
    assert call(gateway, "list_signs_and_scenes", {})["data"]["now"]["signs"][0]["shown"] == "face_missing"


def test_a_re_exported_model_is_never_shown_from_a_stale_browser_cache(client, tmp_path, monkeypatch):
    glb = tmp_path / "model_colored.glb"
    glb.write_bytes(b"glTF" + b"\0" * 60)
    monkeypatch.setattr(server, "_resolve_assembly_model_path", lambda number, revision: glb)
    monkeypatch.setattr(server, "_motion_entry", lambda number: None)
    first = client.get(f"/api/assembly-model/{ENGINE}")
    assert first.status_code == 200 and first.content == glb.read_bytes()
    assert first.headers["cache-control"] == "no-cache" and first.headers["etag"]
    again = client.get(f"/api/assembly-model/{ENGINE}", headers={"If-None-Match": first.headers["etag"]})
    assert again.status_code == 304 and again.content == b"" and again.headers["etag"] == first.headers["etag"]
    glb.write_bytes(b"glTF" + b"\1" * 80)  # a new export
    changed = client.get(f"/api/assembly-model/{ENGINE}", headers={"If-None-Match": first.headers["etag"]})
    assert changed.status_code == 200 and len(changed.content) == 84
    page = (server.REPO_ROOT / "static" / "index.html").read_text(encoding="utf-8-sig")
    start = page.index("THREE.GLTFLoader = class {")
    loader = page[start:page.index("        parse(data) {", start)]
    assert "fetch(url, { cache: 'no-cache' })" in loader and "FileLoader" not in loader
