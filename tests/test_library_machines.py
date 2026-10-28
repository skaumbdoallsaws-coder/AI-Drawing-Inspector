"""Library machines open as assemblies (docs/specification-sheet-slots-plan.md, SS5): the library search, the bodies
read from the GLB, the opened-machines registry, the routes, the spec sheet's CAD values, the documents offered,
and Sage's find and open tools. No credentials or inference."""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.assembly_knowledge.library_machines import (
    LibraryMachineRegistry, glb_body_names, glb_zone_bodies, search_library_machines,
)
from ai_inspector.specification_sheet.cad import glb_extents
from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway

REPO = Path(server.REPO_ROOT)
MORI = "asset-lathe-mori-cl200a"
PRINCIPAL = SimpleNamespace(tenant_id="tenant", principal_id="user", roles=(), allowed_site_ids=())


@pytest.fixture
def client(tmp_path, monkeypatch):
    registry = LibraryMachineRegistry(tmp_path / "library_machines.json")
    monkeypatch.setattr(server, "_library_machine_registry", lambda: registry)
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "sheets")
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "0")
    yield TestClient(server.app)
    for asset_id in registry.ids():
        server.assembly_profiles.pop(asset_id, None)
        server.prepared_assembly_sources.pop(asset_id, None)


def _glb(path, names):
    document = json.dumps({"asset": {"version": "2.0"}, "meshes": [{"primitives": []}],
                           "nodes": [({"name": name} if name is not None else {}) | {"mesh": 0} for name in names]
                           + [{"name": "group", "children": [0]}]}).encode()
    document += b" " * (-len(document) % 4)
    path.write_bytes(b"glTF" + struct.pack("<II", 2, 20 + len(document)) + struct.pack("<II", len(document),
                                                                                         0x4E4F534A) + document)
    return path


def test_the_library_is_searched_by_name_tags_and_category():
    assert MORI in [row["assetId"] for row in search_library_machines(REPO, "cnc lathe")]
    assert "asset-reversible-fork-lift-truck" in [row["assetId"] for row in search_library_machines(REPO, "forklift")]
    assert all(row["category"] == "Machines" for row in search_library_machines(REPO, "", category="Machines"))
    assert not [row for row in search_library_machines(REPO, "", limit=50) if row["category"] == "People"]


def test_bodies_are_the_named_mesh_nodes_and_shared_or_empty_names_are_left_to_the_whole_model(tmp_path):
    path = _glb(tmp_path / "model.glb", ["frame", "door", "Door", None, "spindle", "ice_bufferzone_extrude"])
    assert glb_body_names(path) == ["frame", "spindle"]
    assert glb_zone_bodies(path) == ["ice_bufferzone_extrude"]


def test_the_clearance_zone_around_a_machine_is_not_in_its_size():
    model = REPO / "generated/industrial_assets/local_library/lathe-mori-cl200a/CL200A_colored.glb"
    whole, machine = glb_extents(model), glb_extents(model, exclude=["ice_bufferzone_extrude"])
    assert round(whole["depth"], 2) == 3.39 and round(machine["depth"], 2) == 2.19
    assert machine["width"] == whole["width"]


def test_a_library_machine_opens_as_an_assembly_with_one_part_per_body_and_stays_after_a_restart(client):
    opened = client.post(f"/api/library-machines/{MORI}/open").json()
    assert opened == {"success": True, "assemblyNumber": MORI, "displayName": "Mori CL-200A CNC Lathe",
                      "category": "Machines", "bodies": 11, "added": True}
    assert client.post(f"/api/library-machines/{MORI}/open").json()["added"] is False
    assert server._library_machine_registry().ids() == [MORI]
    context = client.get(f"/api/assembly-context/{MORI}").json()
    assert context["context_kind"] == "assembly" and context["has_glb"]
    assert context["library_machine"]["category"] == "Machines" and len(context["occurrences"]) == 11
    assert context["library_machine"]["zoneBodies"] == ["ice_bufferzone_extrude"]
    assert context["occurrences"][0]["name"] == "extrusion_machine_extrude"
    assert client.get(f"/api/assembly-model/{MORI}").content[:4] == b"glTF"
    listed = [row for row in client.get("/api/profiles").json() if row["part_number"] == MORI]
    assert listed and listed[0]["source"] == "library_machine"
    assert [row["assetId"] for row in client.get("/api/library-machines", params={"q": "mori"}).json()[
        "machines"] if row["opened"]] == [MORI]
    server.assembly_profiles.pop(MORI)
    server._load_assembly_profiles()  # as after a restart
    assert MORI in server.assembly_profiles
    assert client.post("/api/library-machines/asset-not-in-the-library/open").status_code == 404


def test_its_specification_sheet_takes_the_size_from_the_model_and_leaves_the_weight_open(client):
    client.post(f"/api/library-machines/{MORI}/open")
    assert client.post(f"/api/specification-sheet/{MORI}/generate?rebaseline=true").status_code == 200
    slots = client.get(f"/api/specification-sheet/{MORI}/slots").json()["slots"]
    assert slots["title"]["value"] == "Mori CL-200A CNC Lathe"
    assert slots["spec.overall_dimensions.value"] == {**slots["spec.overall_dimensions.value"],
                                                      "value": "101.5 x 86.3 x 90 in", "source": "cad"}
    assert slots["spec.weight.value"]["open"]
    host = server._DOCUMENTATION_AGENT_HOST
    assert host.state(MORI, "product_specification_sheet")["ok"]
    for document_type in ("illustrated_parts_manual", "operations_and_maintenance_manual", "work_instructions",
                          "inspection_sheet"):
        refused = host.state(MORI, document_type)
        assert refused["code"] == "library_machine_bodies" and "bodies, not numbered parts" in refused["message"]


def test_its_exported_sheet_is_named_after_the_machine_not_its_asset_id(client):
    from tests.test_specification_sheet_slots import _render

    client.post(f"/api/library-machines/{MORI}/open")
    document = client.post(f"/api/specification-sheet/{MORI}/generate?rebaseline=true").json()["document"]
    assert _render(client, MORI, document).status_code == 200
    gateway = DocumentationGateway(server._DOCUMENTATION_AGENT_HOST, PRINCIPAL,
                                   {"assemblyNumber": MORI, "documentType": "product_specification_sheet"},
                                   turn_id="turn", user_message="Export the spec sheet")
    assert asyncio.run(gateway.call("export_specification_sheet", {}))["ok"]
    assert [card["fileName"] for card in gateway.files] == ["Mori CL-200A CNC Lathe specification sheet.pdf"]


def test_sage_finds_a_machine_and_opens_it_after_the_reply_even_with_no_assembly_loaded(client):
    gateway = DocumentationGateway(server._DOCUMENTATION_AGENT_HOST, PRINCIPAL,
                                   {"assemblyNumber": None, "documentType": None}, turn_id="turn",
                                   user_message="Make a spec sheet for the Mori lathe")
    found = asyncio.run(gateway.call("find_library_machines", {"query": "mori lathe"}))
    assert [row["assetId"] for row in found["data"]["machines"]] == [MORI]
    opened = asyncio.run(gateway.call("open_library_machine", {"assetId": MORI}))
    assert opened["ok"] and opened["data"]["bodies"] == 11
    assert gateway.queued == [{"name": "open_library_machine", "args": {"asset_id": MORI}}]
    again = asyncio.run(gateway.call("open_library_machine", {"assetId": "asset-reversible-fork-lift-truck"}))
    assert again["error"]["code"] == "documentation_workflow_already_queued"
    unknown = DocumentationGateway(server._DOCUMENTATION_AGENT_HOST, PRINCIPAL,
                                   {"assemblyNumber": None, "documentType": None}, turn_id="turn2")
    assert asyncio.run(unknown.call("open_library_machine", {"assetId": "asset-nothing-like-it"}))["error"][
        "code"] == "library_machine_unknown"


def test_the_assembly_tab_sage_finds_a_machine_and_loads_it_in_the_3d_view(client):
    from jsonschema import Draft202012Validator
    from ai_inspector.documentation.agent_tools import OPEN_LIBRARY_MACHINE

    gateway = DocumentationGateway(server._DOCUMENTATION_AGENT_HOST, PRINCIPAL,
                                   {"assemblyNumber": None, "documentType": None}, turn_id="turn",
                                   user_message="Load the Mori lathe", workspace="assembly")
    found = asyncio.run(gateway.call("find_library_machines", {"query": "mori lathe"}))
    assert [row["assetId"] for row in found["data"]["machines"]] == [MORI]
    opened = asyncio.run(gateway.call("open_library_machine", {"assetId": MORI}))
    assert opened["ok"] and "3D view" in opened["data"]["note"]
    assert gateway.queued == [{"name": "open_library_machine", "args": {"asset_id": MORI, "view": "assembly"}}]
    Draft202012Validator(OPEN_LIBRARY_MACHINE["input_schema"]).validate(gateway.queued[0]["args"])
    # Finishes in the same reply would land on the machine loaded now, not on the one that opens after it.
    refused = asyncio.run(gateway.call("set_assembly_appearance", {"assignments": [
        {"target": "whole", "appearanceId": "paint-safety-yellow"}]}))
    assert refused["error"]["code"] == "appearance_machine_opening" and gateway.appearance_changes == []


def test_the_page_opens_library_machines_and_offers_only_their_specification_sheet():
    page = (REPO / "static" / "index.html").read_text(encoding="utf-8")
    for needle in ("async function _libraryMachineOpen(", "function _libraryMachinePicker(",
                   "_libraryMachineDropdownSearch(q);", "open_library_machine: {", "'open_library_machine',",
                   "documentationLibraryMachineRibbon", "Open a library machine",
                   "assemblyContext?.library_machine && selected.value !== 'product_specification_sheet'",
                   "partMeshMap.__library_bodies__", "assemblyContext?.library_machine?.zoneBodies",
                   "addNotificationMessage(`Library machine ${name} opened: ${bodies}",
                   "{ documentation: args?.view !== 'assembly' }"):
        assert needle in page, needle
    assert "open_library_machine" in {spec["name"] for spec in server.AGENT_TOOL_SPECS["inspector"]}
