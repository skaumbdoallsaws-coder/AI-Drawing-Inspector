"""Smart Dimension (docs/assembly-smart-dimension-plan.md, D2-D3): dimensions kept with the assembly's appearance
but outside its revision, the route the Assembly view saves them through, what the view reports of them and of each
face's exact surface, the server's measurements (the cases shared with the JavaScript tests), and Sage's tools
measuring, placing and removing dimensions on faces. No credentials or inference."""
from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.assembly_knowledge import assembly_dimensions
from ai_inspector.assembly_knowledge.assembly_appearance import (
    AssemblyAppearanceError, AssemblyAppearanceStore, dimension, dimensions_revision, revision,
)
from ai_inspector.codex_runtime.progress import describe
from tests.test_assembly_faces import PRINT_SIDE, PRINT_TOP, FaceHost, face_row
from tests.test_assembly_signs_scenes import ENGINE
from tests.test_codex_assembly_appearance_tools import PARTS
from tests.test_codex_documentation_tools import PRINCIPAL, call
from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway

CASES = json.loads((Path(__file__).parent / "fixtures" / "smart_dimension_cases.json").read_text(encoding="utf-8"))
FACE = {"type": "face", "part": "door", "mesh": 0, "face": 3, "fingerprint": PRINT_TOP}
EDGE = {"type": "edge", "part": "frame", "mesh": 1, "at": [0.1, 0.2, 0.3],
        "faces": [{"face": 2, "fingerprint": PRINT_SIDE}, None]}


@pytest.mark.parametrize("case", CASES["cases"], ids=[case["name"] for case in CASES["cases"]])
def test_the_server_measures_the_shared_cases_as_the_view_does(case):
    entities = [assembly_dimensions.face_entity(row) for row in case["faces"]]
    expect = case["expect"]
    if expect.get("error"):
        with pytest.raises(assembly_dimensions.DimensionError, match="no size of its own"):
            assembly_dimensions.measure(*entities)
        return
    found = assembly_dimensions.measure(*entities)
    assert found["kind"] == expect["kind"] and bool(found.get("sphere")) == bool(expect.get("sphere"))
    if expect.get("method"):
        assert found["method"] == expect["method"]
    assert assembly_dimensions.format_value(found, "mm") == expect["mm"]
    assert assembly_dimensions.format_value(found, "in") == expect["in"]


def test_a_face_without_an_exact_surface_measures_nothing():
    assert assembly_dimensions.face_entity({"center": [0, 0, 0], "kind": "cone"}) is None
    assert assembly_dimensions.face_entity({"center": [0, 0, 0], "geometry": {"kind": "torus"}}) is None
    described = assembly_dimensions.described({"kind": "distance", "value": 0.25, "method": "parallel"}, "in")
    assert described == {"kind": "distance", "text": "9.84", "value": 9.8425, "unit": "in", "method": "parallel"}
    assert assembly_dimensions.described({"kind": "diameter", "sphere": True, "value": 0.1})["kind"] == \
        "sphere diameter"


def test_a_dimension_names_one_or_two_faces_edges_or_vertices_on_a_copy_of_a_part():
    row = dimension({"entities": [FACE, EDGE], "text": [0, 1, 0], "label": " deck to frame "}, parts=PARTS)
    assert row["dimId"].startswith("dm-") and row["label"] == "deck to frame" and row["text"] == [0, 1, 0]
    assert row["entities"][0] == FACE and row["entities"][1]["faces"][1] is None
    assert dimension({"dimId": "dm-abcdef1234", "entities": [{"type": "vertex", "part": "door", "at": [0, 0, 0]}],
                      "text": None}, parts=PARTS)["entities"][0] == {"type": "vertex", "part": "door", "mesh": 0,
                                                                   "at": [0, 0, 0]}
    for bad, message in (({"entities": []}, "one or two"), ({"entities": [FACE] * 3}, "one or two"),
                         ({"dimId": "sg-abcdef", "entities": [FACE]}, "dimId"),
                         ({"entities": [dict(FACE, part="wheel")]}, "not a part"),
                         ({"entities": [dict(FACE, type="hole")]}, "type"),
                         ({"entities": [{"type": "vertex", "part": "door"}]}, "point"),
                         ({"entities": [dict(EDGE, faces=[None, None])]}, "an edge needs"),
                         ({"entities": [dict(FACE, fingerprint=None)]}, "fingerprint")):
        with pytest.raises(AssemblyAppearanceError, match=message):
            dimension(bad, parts=PARTS)


def test_dimensions_are_kept_with_the_appearance_but_outside_its_revision(tmp_path):
    store = AssemblyAppearanceStore(tmp_path)
    painted = store.write("tricycle", None, {"door": {"appearanceId": "paint-safety-orange"}}, part_numbers=PARTS,
                          by="test")
    before = revision(painted)
    assert painted["dimensions"] == [] and dimensions_revision(painted) == ""
    dimensioned = store.set_dimensions("tricycle", [{"entities": [FACE]}, {"entities": [FACE, EDGE]}],
                                       part_numbers=PARTS, by="test")
    assert revision(dimensioned) == before, "the Specification Sheet's picture does not show dimensions"
    first = dimensions_revision(dimensioned)
    assert first and len(dimensioned["dimensions"]) == 2 and dimensioned["dimensionUnits"] == "mm"
    inches = store.set_dimensions("tricycle", dimensioned["dimensions"], units="in", part_numbers=PARTS, by="test")
    assert inches["dimensionUnits"] == "in" and dimensions_revision(inches) != first
    kept = store.set_dimensions("tricycle", inches["dimensions"][:1], part_numbers=PARTS, by="test")
    assert kept["dimensionUnits"] == "in", "units stay unless given"
    assert store.write("tricycle", None, {}, part_numbers=PARTS, by="test")["dimensions"] == kept["dimensions"]
    assert store.clear("tricycle", by="test")["dimensions"] == kept["dimensions"], "a reset keeps the dimensions"
    assert store.read("tricycle")["dimensions"] == kept["dimensions"], "a document of dimensions alone is kept"
    shown = store.view(store.read("tricycle")) if hasattr(store, "view") else server.assembly_appearance_view(
        store.read("tricycle"))
    assert shown["dimensions"] == kept["dimensions"] and shown["dimensionUnits"] == "in"
    assert shown["dimensionsRevision"] == dimensions_revision(kept)
    with pytest.raises(AssemblyAppearanceError, match="its own dimId"):
        store.set_dimensions("tricycle", [dict(kept["dimensions"][0])] * 2, part_numbers=PARTS, by="test")
    with pytest.raises(AssemblyAppearanceError, match="at most 100"):
        store.set_dimensions("tricycle", [{"entities": [FACE]}] * 101, part_numbers=PARTS, by="test")
    with pytest.raises(AssemblyAppearanceError, match="units"):
        store.set_dimensions("tricycle", [], units="cm", part_numbers=PARTS, by="test")
    assert store.set_dimensions("tricycle", [], units="mm", part_numbers=PARTS, by="test")["dimensions"] == []


def test_the_view_reports_each_dimension_s_value_and_each_face_s_exact_surface(tmp_path):
    store = AssemblyAppearanceStore(tmp_path)
    reported = store.write_geometry("tricycle", {"dimensions": {
        "dm-abcdef1234": {"status": "drawn", "kind": "length", "value": 0.99833629708, "text": "998.34"},
        "dm-bbbbbb2222": {"status": "dimension_missing"},
        "dm-cccccc3333": {"status": "melted"}, "x": {"status": "drawn"},
        "dm-dddddd4444": {"status": "drawn", "kind": "angle", "value": float("nan")}}}, part_numbers=PARTS)
    assert reported["dimensions"] == {
        "dm-abcdef1234": {"status": "drawn", "kind": "length", "value": 0.998336297, "text": "998.34"},
        "dm-bbbbbb2222": {"status": "dimension_missing"}, "dm-dddddd4444": {"status": "drawn"}}
    cylinder = {"kind": "cylinder", "point": [0, 0.5, 0], "axis": [0, 1, 0], "radius": 0.016}
    faces = store.write_face_report("tricycle", {"parts": {"door": {"faceCount": 3, "faces": [
        face_row(3, PRINT_TOP, kind="plane", geometry={"kind": "plane", "point": [0, 1, 0], "normal": [0, 1, 0]}),
        face_row(4, PRINT_TOP, kind="cylinder", geometry=cylinder),
        face_row(5, PRINT_SIDE, kind="cone", geometry={"kind": "cone", "apex": [0, 0, 0]})]}}}, part_numbers=PARTS)
    rows = faces["parts"]["door"]["faces"]
    assert rows[0]["geometry"]["kind"] == "plane" and rows[1]["geometry"] == cylinder and "geometry" not in rows[2]
    with pytest.raises(AssemblyAppearanceError, match="direction"):
        store.write_face_report("tricycle", {"parts": {"door": {"faces": [face_row(3, PRINT_TOP, geometry={
            "kind": "plane", "point": [0, 0, 0], "normal": [0, 2, 0]})]}}}, part_numbers=PARTS)


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "ASSEMBLY_APPEARANCE_ROOT", tmp_path / "appearances")
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "sheets")
    return TestClient(server.app)


def test_the_view_saves_dimensions_and_reports_them_through_the_routes(client):
    part = next(iter(server._assembly_appearance_parts(ENGINE)))
    url = f"/api/assembly-appearance/{ENGINE}"
    row = {"entities": [dict(FACE, part=part)], "text": [0.1, 0.2, 0.3]}
    saved = client.put(url + "/dimensions", json={"dimensions": [row], "units": "in"})
    body = saved.json()
    assert saved.status_code == 200 and body["success"] and body["dimensionUnits"] == "in"
    assert body["dimensions"][0]["entities"][0]["face"] == 3 and body["dimensionsRevision"]
    shown = client.get(url).json()
    assert shown["dimensions"] == body["dimensions"] and shown["dimensionsRevision"] == body["dimensionsRevision"]
    assert client.put(url + "/dimensions", json={"dimensions": body["dimensions"]}).json()["dimensionUnits"] == "in"
    bad = client.put(url + "/dimensions", json={"dimensions": [{"entities": [dict(FACE, part="no-such-part")]}]})
    assert bad.status_code == 400 and "not a part" in bad.json()["message"]
    assert client.put("/api/assembly-appearance/999999999/dimensions", json={"dimensions": []}).status_code == 404
    dim_id = body["dimensions"][0]["dimId"]
    measured = client.put(url + "/geometry", json={"dimensions": {dim_id: {"status": "drawn", "kind": "distance",
                                                                           "value": 0.25, "text": "9.84"}}})
    assert measured.status_code == 200
    assert server._assembly_appearance_store().read_geometry(ENGINE)["dimensions"][dim_id]["text"] == "9.84"


# -- Sage ----------------------------------------------------------------------------------------------------------

DECK_TOP = face_row(3, PRINT_TOP, kind="plane", areaM2=0.5, center=[0, 1.37, 0], side="top",
                    geometry={"kind": "plane", "point": [0, 1.37, 0], "normal": [0, 1, 0]})
BASE_TOP = face_row(5, PRINT_SIDE, kind="plane", areaM2=0.07, center=[0.1, 0.0, 0.2], side="top",
                    geometry={"kind": "plane", "point": [0, 0.0013, 0], "normal": [0, 1, 0]})
HOLE = face_row(9, {"area": 0.004, "center": [0, 0, 0], "normal": [0, 0, 0.1]}, kind="cylinder", areaM2=0.004,
                center=[0.016, 0.7, 0.4], radiusM=0.016,
                geometry={"kind": "cylinder", "point": [0, 0.7, 0.4], "axis": [1, 0, 0], "radius": 0.016})
CONE = face_row(11, {"area": 0.002, "center": [0, 0, 0], "normal": [0, 0, 1]}, kind="cone", areaM2=0.002,
                center=[0, 0.2, 0])
OLD_PLANE = face_row(12, {"area": 0.001, "center": [0, 0, 0], "normal": [1, 0, 0]}, kind="plane", areaM2=0.001,
                     center=[0, 0.3, 0])


class DimensionHost(FaceHost):
    """The documentation host with dimensions, as _DocumentationAgentHost has them."""

    def write_assembly_dimensions(self, number, dimensions, units=None):
        extra = {} if units is None else {"units": units}
        return self.store.set_dimensions(number, dimensions, part_numbers=PARTS, by="sage", **extra)


def dimension_gateway(tmp_path):
    host = DimensionHost(tmp_path)
    host.store.write_face_report("tricycle", {"parts": {
        "door": {"faceCount": 12, "copies": 1, "faces": [DECK_TOP, HOLE, CONE, OLD_PLANE]},
        "frame": {"faceCount": 8, "copies": 1, "faces": [BASE_TOP]}}}, part_numbers=PARTS)
    return host, DocumentationGateway(host, PRINCIPAL, {"assemblyNumber": "tricycle", "documentType": None},
                                      turn_id="turn", workspace="assembly", max_calls=30)


def test_sage_measures_faces_as_the_view_does(tmp_path):
    _host, gateway = dimension_gateway(tmp_path)
    data = call(gateway, "measure_assembly", {"measurements": [
        {"faces": [{"part": "door", "face": 3}, {"part": "frame", "face": 5}]},
        {"faces": [{"part": "door", "face": 9}]},
        {"faces": [{"part": "door", "face": 3}]},
        {"faces": [{"part": "door", "face": 11}]},
        {"faces": [{"part": "door", "face": 12}]},
        {"faces": [{"part": "door", "face": 44}]},
        {"faces": [{"part": "wheel", "face": 1}]}]})["data"]
    found = data["measurements"]
    assert found[0] == {"faces": [{"part": "door", "mesh": 0, "face": 3}, {"part": "frame", "mesh": 0, "face": 5}],
                        "kind": "distance", "text": "1368.70", "value": 1368.7, "unit": "mm", "method": "parallel"}
    assert found[1]["text"] == "\u00d832.00" and found[1]["kind"] == "diameter"
    assert "no size of its own" in found[2]["error"]
    assert "cone face" in found[3]["error"] and "Smart Dimension" in found[3]["error"]
    assert "not reported the exact surface" in found[4]["error"]
    assert "list_part_faces" in found[5]["error"] and "not a part" in found[6]["error"]
    assert data["units"] == "mm" and data["dimensions"] == []
    inches = call(gateway, "measure_assembly", {"measurements": [{"faces": [{"part": "door", "face": 9}]}],
                                                "units": "in"})["data"]
    assert inches["measurements"][0]["text"] == "\u00d81.26" and inches["measurements"][0]["unit"] == "in"
    assert describe("measure_assembly", {})["running"] == "Measuring the machine's faces"


def test_sage_places_dimensions_on_faces_lists_what_the_view_drew_and_removes_them(tmp_path):
    host, gateway = dimension_gateway(tmp_path)
    painted = host.store.write("tricycle", None, {"door": {"appearanceId": "paint-safety-orange"}},
                               part_numbers=PARTS, by="test")
    user = host.store.set_dimensions("tricycle", [{"entities": [EDGE], "text": [0, 1, 0]}], part_numbers=PARTS,
                                     by="workspace")["dimensions"][0]
    placed = call(gateway, "place_assembly_dimensions", {"dimensions": [
        {"faces": [{"part": "door", "face": 3}, {"part": "frame", "face": 5}], "label": "deck height"},
        {"faces": [{"part": "door", "face": 9}]}]})
    assert placed["ok"], placed
    rows = placed["data"]["placed"]
    assert [(row["label"] if "label" in row else None, row["text"]) for row in rows] == [
        ("deck height", "1368.70"), (None, "\u00d832.00")]
    assert placed["data"]["dimensionCount"] == 3 and gateway.appearance_changes == ["tricycle"]
    stored = host.store.read("tricycle")
    assert stored["dimensions"][0] == user, "the user's dimension stays"
    assert stored["dimensions"][1]["entities"] == [
        {"type": "face", "part": "door", "mesh": 0, "face": 3, "fingerprint": PRINT_TOP},
        {"type": "face", "part": "frame", "mesh": 0, "face": 5, "fingerprint": PRINT_SIDE}]
    assert stored["dimensions"][1]["text"] is None, "the view puts the text beside the dimension"
    assert revision(stored) == revision(painted), "dimensions leave the finishes' revision alone"
    refused = call(gateway, "place_assembly_dimensions", {"dimensions": [
        {"faces": [{"part": "door", "face": 9}]}, {"faces": [{"part": "door", "face": 3}]}]})
    assert refused["error"]["code"] == "dimension_nothing_to_measure"
    assert len(host.store.read("tricycle")["dimensions"]) == 3, "all or nothing"
    host.store.write_geometry("tricycle", {"dimensions": {
        user["dimId"]: {"status": "drawn", "kind": "length", "value": 0.5, "text": "500.00"},
        rows[0]["dimId"]: {"status": "dimension_missing"}}}, part_numbers=PARTS)
    listed = call(gateway, "measure_assembly", {})["data"]["dimensions"]
    assert listed[0] == {"dimId": user["dimId"], "measures": [{"part": "frame", "mesh": 1, "type": "edge"}],
                         "shown": "drawn", "kind": "length", "text": "500.00"}
    assert listed[1]["label"] == "deck height" and listed[1]["shown"] == "dimension_missing"
    assert listed[2]["shown"] == "not drawn yet"
    assert call(gateway, "inspect_assembly", {})["data"]["dimensionCount"] == 3
    inches = call(gateway, "place_assembly_dimensions", {"replace": True, "units": "in", "dimensions": [
        {"faces": [{"part": "door", "face": 9}]}]})["data"]
    assert inches["units"] == "in" and inches["placed"][0]["text"] == "\u00d81.26" and inches["dimensionCount"] == 1
    assert call(gateway, "remove_assembly_dimensions", {"dimIds": ["dm-zzzzzz9999"]})["error"]["code"] == \
        "dimension_unknown"
    removed = call(gateway, "remove_assembly_dimensions", {"all": True})["data"]
    assert removed == {"set": True, "removed": 1, "dimensionCount": 0}
    assert host.store.read("tricycle")["dimensionUnits"] == "in", "removing keeps the units"
    assert describe("place_assembly_dimensions", {"dimensions": [{}, {}]})["running"] == \
        "Placing 2 dimensions on the machine"
    assert describe("remove_assembly_dimensions", {"all": True})["done"] == "Removed the machine's dimensions"


def test_sage_waits_for_a_library_machine_to_open_before_dimensioning_it(tmp_path):
    _host, gateway = dimension_gateway(tmp_path)
    gateway.queued.append({"name": "open_library_machine", "arguments": {}})
    refused = call(gateway, "place_assembly_dimensions", {"dimensions": [{"faces": [{"part": "door", "face": 9}]}]})
    assert refused["error"]["code"] == "appearance_machine_opening"
