"""Sage on Codex in the 3D Model tab (part_tools.py): the part shown, its CAD features, highlighting features after
the reply, finishes on features and faces and Smart Dimensions, said in features over the Assembly tab's tools; and
the part's appearance routes the tab saves through. No credentials or inference."""
from __future__ import annotations

import json

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator
import pytest

import server
from ai_inspector.assembly_knowledge.assembly_appearance import AssemblyAppearanceStore
from ai_inspector.codex_runtime import documentation_pilot
from ai_inspector.codex_runtime.mcp_bridge import explicit_types
from ai_inspector.codex_runtime.part_tools import PART_NAMES, PartGateway, tool_specs
from ai_inspector.codex_runtime.policy import PilotError
from ai_inspector.codex_runtime.progress import describe
from tests.test_assembly_faces import PRINT_SIDE, PRINT_TOP, face_row
from tests.test_codex_documentation_tools import PRINCIPAL, Host, call
from tests.test_codex_mcp_schema_types import untyped_nodes

FEATURES = {"extrusion_boss_extrude1": "Boss-Extrude1", "ice_cut_extrude1": "Cut-Extrude1",
            "mirrorsolid_mirror1": "Mirror1", "__base__": "Base body"}


class PartHost(Host):
    """The 3D Model tab's host, as _PartAgentHost has it: the part's features stand where an assembly's parts do."""

    def __init__(self, root):
        super().__init__()
        self.store = AssemblyAppearanceStore(root)

    def assembly(self, number):
        if number != "100002":
            raise LookupError(number)
        return {"partNumber": number, "name": "Bracket", "featureCount": 3, "sourceRevision": "1"}

    def part_features(self, number):
        return [{"feature": key, "name": label, "type": "Extrusion", "color": "#ff0000", "colorName": "Red",
                 "faceCount": 6, "parameters": {"depth": 0.01}} for key, label in FEATURES.items()
                if key != "__base__"]

    def part_physical(self, number):
        return {"material": "6061 Alloy", "massKg": 0.12, "note": "As the CAD export gives them."}

    def assembly_appearance(self, number):
        return self.store.read(number)

    def assembly_parts(self, number):
        return dict(FEATURES)

    def write_assembly_appearance(self, number, whole, parts, faces=None):
        extra = {} if faces is None else {"faces": faces}
        return self.store.write(number, whole, parts, part_numbers=FEATURES, by="sage", **extra)

    def assembly_geometry(self, number):
        return self.store.read_geometry(number)

    def assembly_face_report(self, number):
        return self.store.read_face_report(number)

    def write_assembly_dimensions(self, number, dimensions, units=None):
        extra = {} if units is None else {"units": units}
        return self.store.set_dimensions(number, dimensions, part_numbers=FEATURES, by="sage", **extra)


@pytest.fixture(autouse=True)
def no_public_research(monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "0")


def gateway(tmp_path, number="100002"):
    host = PartHost(tmp_path)
    return host, PartGateway(host, PRINCIPAL, {"assemblyNumber": number, "documentType": None}, turn_id="turn",
                             max_calls=30)


def test_the_3d_model_tab_has_only_the_part_tools_typed_and_closed():
    specs = tool_specs()
    assert tuple(spec["name"] for spec in specs) == PART_NAMES
    for spec in specs:
        typed = explicit_types(spec["input_schema"])
        Draft202012Validator.check_schema(typed)
        assert untyped_nodes(typed) == [] and spec["input_schema"]["additionalProperties"] is False, spec["name"]
        assert "assembly" not in spec["description"].lower() and "machine" not in spec["description"].lower(), \
            spec["name"]
    assert [spec["name"] for spec in specs if not spec.get("read_only", True)] == [
        "highlight_part_features", "set_part_appearance", "place_part_dimensions", "remove_part_dimensions"]


def test_inspect_part_reads_the_features_what_is_on_the_part_and_what_is_highlighted(tmp_path):
    host, reader = gateway(tmp_path)
    data = call(reader, "inspect_part", {})["data"]
    assert data["partNumber"] == "100002" and data["name"] == "Bracket" and data["featureCount"] == 3
    assert [row["feature"] for row in data["features"]] == list(FEATURES)[:3]
    assert data["physical"]["material"] == "6061 Alloy" and data["highlightedNow"] == []
    assert data["finishes"] == {"whole": None, "features": {}} and data["dimensionCount"] == 0
    host.store.write_geometry("100002", {"view": {"shown": "group", "parts": ["ice_cut_extrude1"], "exploded": False,
                                                  "label": "highlighted"}}, part_numbers=FEATURES)
    assert call(reader, "inspect_part", {})["data"]["highlightedNow"] == ["ice_cut_extrude1"]


def test_features_are_highlighted_after_the_reply_by_id_or_name_and_cleared(tmp_path):
    _host, reader = gateway(tmp_path)
    shown = call(reader, "highlight_part_features", {"features": ["extrusion_boss_extrude1", "cut-extrude1"]})
    assert shown["ok"] and shown["data"]["runsAfterReply"]
    assert shown["data"]["highlights"] == [{"feature": "extrusion_boss_extrude1", "name": "Boss-Extrude1"},
                                           {"feature": "ice_cut_extrude1", "name": "Cut-Extrude1"}]
    assert reader.queued == [{"name": "highlight_features", "args": {
        "feature_ids": ["extrusion_boss_extrude1", "ice_cut_extrude1"]}}]
    refused = call(reader, "highlight_part_features", {"features": ["Fillet9"]})
    assert not refused["ok"] and refused["error"]["code"] == "highlight_unknown_feature"
    assert len(reader.queued) == 1, "a refused highlight leaves the earlier one"
    cleared = call(reader, "highlight_part_features", {"clear": True})
    assert cleared["ok"] and reader.queued == [{"name": "clear_feature_highlights", "args": {}}], \
        "one highlight or clear per reply"
    both = call(reader, "highlight_part_features", {"clear": True, "features": ["Mirror1"]})
    assert both["error"]["code"] == "highlight_clear_with_features"
    assert call(reader, "highlight_part_features", {})["error"]["code"] == "highlight_nothing"


def test_finishes_go_on_the_whole_part_features_and_faces_in_features_words(tmp_path):
    host, reader = gateway(tmp_path)
    host.store.write_face_report("100002", {"parts": {"extrusion_boss_extrude1": {"faceCount": 6, "copies": 1,
                                 "faces": [face_row(3, PRINT_TOP, kind="plane", areaM2=0.12, center=[0, 1, 0],
                                                    side="top", approximate=True),
                                           face_row(5, PRINT_SIDE, kind="plane", areaM2=0.03, center=[0.1, 0, 0],
                                                    side="right", approximate=True)]}}},
                                 part_numbers=FEATURES)
    listed = call(reader, "list_appearances", {"query": "orange"})["data"]
    assert listed["features"][0] == {"feature": "extrusion_boss_extrude1", "name": "Boss-Extrude1"}
    assert "parts" not in listed and "part's" in listed["note"]
    faces = call(reader, "list_part_faces", {"feature": "extrusion_boss_extrude1"})["data"]
    assert [row["face"] for row in faces["faces"]] == [3, 5] and "smooth patches" in faces["note"]
    unknown = call(reader, "list_part_faces", {"feature": "Fillet9"})
    assert not unknown["ok"] and "not a feature of" in unknown["error"]["message"]
    painted = call(reader, "set_part_appearance", {"assignments": [
        {"target": "whole", "appearanceId": "paint-machine-gray"},
        {"target": "features", "features": ["ice_cut_extrude1"], "appearanceId": "paint-safety-orange"},
        {"target": "faces", "faces": [{"feature": "extrusion_boss_extrude1", "face": 3}],
         "appearanceId": "paint-safety-yellow"}]})
    assert painted["ok"], painted
    stored = host.store.read("100002")
    assert stored["parts"] == {"ice_cut_extrude1": {"appearanceId": "paint-safety-orange"}}
    assert stored["faces"][0]["part"] == "extrusion_boss_extrude1" and stored["faces"][0]["fingerprint"] == PRINT_TOP
    assert painted["data"]["faces"][0]["feature"] == "extrusion_boss_extrude1"
    assert "3D Model view" in painted["data"]["note"]
    refused = call(reader, "set_part_appearance", {"assignments": [
        {"target": "features", "features": ["Fillet9"], "appearanceId": "paint-safety-orange"}]})
    assert not refused["ok"] and "feature" in refused["error"]["message"]
    assert "Assembly" not in refused["error"]["message"]


def test_a_part_without_a_feature_model_or_none_shown_is_said_plainly(tmp_path):
    with pytest.raises(PilotError) as refused:
        gateway(tmp_path, number="999999")
    assert refused.value.code == "part_model_unavailable" and refused.value.status_code == 409, \
        "the turn ends before Sage runs, with a plain reason"
    _host, reader = gateway(tmp_path, number=None)
    assert call(reader, "inspect_part", {})["error"]["code"] == "part_required"
    assert call(reader, "set_assembly_scene", {"sceneId": "classic"})["error"]["code"] in (
        "codex_tool_denied", "codex_tool_unknown")


def test_the_part_binding_comes_from_the_chat_request_and_the_progress_says_part():
    assert documentation_pilot.part_binding({"part_number": "100002"}) == {"assemblyNumber": "100002",
                                                                           "documentType": None}
    assert documentation_pilot.part_binding({}) == {"assemblyNumber": None, "documentType": None}
    with pytest.raises(PilotError):
        documentation_pilot.part_binding({"part_number": "../etc"})
    assert "Highlight" in documentation_pilot.PART_INSTRUCTIONS or "highlight" in documentation_pilot.PART_INSTRUCTIONS
    for name, args in (("inspect_part", {}), ("highlight_part_features", {"features": ["a"]}),
                       ("highlight_part_features", {"clear": True}),
                       ("set_part_appearance", {"assignments": [{"target": "whole"}]}),
                       ("set_part_appearance", {"clear": True}), ("measure_part", {}),
                       ("place_part_dimensions", {"dimensions": [{}]}), ("remove_part_dimensions", {"all": True})):
        step = describe(name, args)
        said = json.dumps(step)
        assert step and ("part" in said or "feature" in said) and "assembly" not in said, (name, step)


@pytest.fixture
def client(tmp_path, monkeypatch):
    colors = tmp_path / "100002_feature_colors.json"
    colors.write_text(json.dumps({"features": [{"glb_node_name": key, "display_label": label}
                                               for key, label in FEATURES.items() if key != "__base__"]}),
                      encoding="utf-8")
    monkeypatch.setattr(server, "PART_APPEARANCE_ROOT", tmp_path / "parts")
    monkeypatch.setattr(server, "_part_feature_colors_path", lambda number: colors if number == "100002" else None)
    return TestClient(server.app)


def test_the_3d_model_tab_saves_the_part_s_finishes_dimensions_and_report(client):
    empty = client.get("/api/part-appearance/100002").json()
    assert empty["success"] and empty["parts"] == {} and empty["dimensions"] == []
    saved = client.put("/api/part-appearance/100002", json={
        "whole": {"appearanceId": "paint-machine-gray"},
        "parts": {"ice_cut_extrude1": {"appearanceId": "paint-safety-orange"}}}).json()
    assert saved["success"] and saved["revision"]
    assert client.get("/api/part-appearance/100002").json()["parts"]["ice_cut_extrude1"]["appearanceId"] == \
        "paint-safety-orange"
    unknown = client.put("/api/part-appearance/100002", json={"parts": {"Fillet9": {"appearanceId": "x"}}})
    assert unknown.status_code == 400
    assert client.put("/api/part-appearance/555/dimensions", json={"dimensions": []}).status_code == 404
    reported = client.put("/api/part-appearance/100002/geometry", json={
        "parts": {"ice_cut_extrude1": {"center": [0, 0, 0], "size": [0.01, 0.01, 0.01]}},
        "view": {"shown": "group", "parts": ["ice_cut_extrude1"], "exploded": False, "label": "highlighted"}})
    assert reported.json()["success"]
    assert server._part_appearance_store().read_geometry("100002")["view"] == {
        "shown": "group", "parts": ["ice_cut_extrude1"], "exploded": False, "label": "highlighted"}, \
        "the view's report reaches Sage (inspect_part's highlightedNow)"
    assert client.put("/api/part-appearance/100002/faces", json={"parts": {}}).json()["success"]
    cleared = client.delete("/api/part-appearance/100002").json()
    assert cleared["success"] and cleared["parts"] == {}


def test_the_3d_model_tab_runs_the_assembly_view_s_tools_on_the_part():
    static = server.Path(server.__file__).parent / "static"
    page = (static / "index.html").read_text("utf-8")
    stream = (static / "chat_stream_runtime.js").read_text("utf-8")
    for needle in (
            # Sage on Codex in the 3D Model tab, its highlight kept until it clears it.
            "status?.partRuntime === 'codex'", "&& originAgent === 'deviation-analyst' && activeMode === '3dmodel');",
            "'highlight_features', 'clear_feature_highlights',",
            "&& !implicitFaiViewportActionsSuppressed && !codexDocumentationTurn",
            "if (sheetWork.workspace === 'part') void _partAppearanceRefresh();",
            # The part's feature model becomes a CAD view: selection, finishes, Smart Dimension.
            "if (glbScene === state.threeLivePartRoot) _partCadBind();",
            "_assemblySelectInstall(container);",
            "_partAppearanceSuspend();",
            "onClick: () => _partDimToolToggle() });",
            "const gFeat = _ribbonGroup('Evaluate');",
            "id=\"partLibraryPanelHost\" hidden",
    ):
        assert needle in page, needle
    assert "'3dmodel'].includes(attachments?.session?.active_mode)" in stream
    assert "codex_part: 'Reading the part'" in stream
    start = page.index("// ===== The part in the 3D Model tab as a CAD view =====")
    assert page[start:page.index("// Build the per-revision GLB URL for the normal 3D Model tab.", start)].isascii()
    assert "chip.textContent = state.partNumber" not in page, "the part's name is in the top bar"
