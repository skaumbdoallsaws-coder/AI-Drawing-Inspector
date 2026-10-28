"""Sage on Codex in the Assembly tab shows a group of parts on its own, exploded or not (show_assembly_parts): the
names are checked on the server and the 3D view runs it after the reply. No credentials or inference."""
from __future__ import annotations

import pytest

from ai_inspector.assembly_knowledge.assembly_appearance import AssemblyAppearanceStore
from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway
from tests.test_codex_assembly_appearance_tools import PARTS, AppearanceHost
from tests.test_codex_documentation_tools import PRINCIPAL, call

GROUPS = [
    {"name": "Door Assembly-1", "description": "Front door", "occurrenceIds": ["o-door-1", "o-spindle-1"],
     "parts": ["door", "spindle"]},
    {"name": "Door Assembly-2", "description": None, "occurrenceIds": ["o-door-2"], "parts": ["door"]},
]


class GroupHost(AppearanceHost):
    def assembly_groups(self, number):
        return [dict(row) for row in GROUPS]

    def assembly_geometry(self, number):
        return self.store.read_geometry(number)


@pytest.fixture(autouse=True)
def no_public_research(monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "0")


def gateway(tmp_path):
    return DocumentationGateway(GroupHost(tmp_path), PRINCIPAL, {"assemblyNumber": "tricycle", "documentType": None},
                                turn_id="turn", workspace="assembly")


def test_parts_are_shown_on_their_own_and_exploded_after_the_reply(tmp_path):
    reader = gateway(tmp_path)
    result = call(reader, "show_assembly_parts", {"parts": ["frame"], "explode": True, "spacing": 1.5})
    assert result["ok"] and result["data"]["runsAfterReply"] and result["data"]["exploded"] is True
    assert reader.queued == [{"name": "show_assembly_parts", "args": {
        "parts": ["frame"], "occurrence_ids": [], "group_parts": [], "explode": True, "spacing": 1.5,
        "label": "Frame"}}]


def test_a_subassembly_is_its_own_occurrences_and_a_name_without_the_instance_is_every_instance(tmp_path):
    reader = gateway(tmp_path)
    assert call(reader, "show_assembly_parts", {"subassemblies": ["Door Assembly-1"]})["ok"]
    assert reader.queued[0]["args"]["occurrence_ids"] == ["o-door-1", "o-spindle-1"]
    assert reader.queued[0]["args"]["label"] == "Door Assembly-1"
    # A later call replaces the earlier one: one view per reply.
    assert call(reader, "show_assembly_parts", {"subassemblies": ["door assembly"], "explode": True})["ok"]
    assert len(reader.queued) == 1
    args = reader.queued[0]["args"]
    assert args["occurrence_ids"] == ["o-door-1", "o-spindle-1", "o-door-2"]
    assert args["group_parts"] == ["door", "spindle"] and args["parts"] == [] and args["explode"] is True


def test_unknown_names_are_refused_and_no_names_show_the_whole_machine(tmp_path):
    reader = gateway(tmp_path)
    refused = call(reader, "show_assembly_parts", {"parts": ["gearbox"]})
    assert not refused["ok"] and refused["error"]["code"] == "show_unknown_part"
    refused = call(reader, "show_assembly_parts", {"subassemblies": ["Gear Assembly"]})
    assert not refused["ok"] and refused["error"]["code"] == "show_unknown_subassembly"
    assert "Door Assembly-1" in refused["error"]["message"]
    whole = call(reader, "show_assembly_parts", {"explode": True})
    assert whole["ok"] and whole["data"]["shows"] == "the whole machine"
    assert reader.queued == [{"name": "show_assembly_parts", "args": {
        "parts": [], "occurrence_ids": [], "group_parts": [], "explode": True, "spacing": 1.0, "label": ""}}]


def test_inspect_assembly_lists_subassemblies_and_what_the_view_shows(tmp_path):
    reader = gateway(tmp_path)
    data = call(reader, "inspect_assembly", {})["data"]
    assert data["subassemblyList"] == [{"name": "Door Assembly-1", "description": "Front door", "partCount": 2},
                                       {"name": "Door Assembly-2", "partCount": 1}]
    assert data["shownNow"] == {"shown": "whole machine", "exploded": False}
    store = AssemblyAppearanceStore(tmp_path)
    store.write_geometry("tricycle", {"view": {"shown": "group", "parts": ["door", "ghost"], "exploded": True,
                                               "label": "Door Assembly-1"}}, part_numbers=PARTS)
    data = call(reader, "inspect_assembly", {})["data"]
    assert data["shownNow"] == {"shown": "group", "parts": ["door"], "exploded": True, "label": "Door Assembly-1"}


def test_the_show_waits_for_a_library_machine_opening_after_the_reply(tmp_path):
    reader = gateway(tmp_path)
    reader.queued.append({"name": "open_library_machine", "args": {"asset_id": "lathe"}})
    refused = call(reader, "show_assembly_parts", {"parts": ["frame"]})
    assert not refused["ok"] and refused["error"]["code"] == "assembly_view_after_open"
