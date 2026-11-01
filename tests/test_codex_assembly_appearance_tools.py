"""Sage's appearance tools (docs/assembly-appearance-plan.md, AP3): finishes from the appearance library written on
the server in Documentation, and the Assembly tab's Sage on the same Codex runtime with only the assembly and
appearance tools. No credentials or inference."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace

from jsonschema import Draft202012Validator
import pytest

from ai_inspector.assembly_knowledge.assembly_appearance import AssemblyAppearanceStore
from ai_inspector.codex_runtime import documentation_pilot
from ai_inspector.codex_runtime.documentation_pilot import inspect_documentation
from ai_inspector.codex_runtime.documentation_tools import ASSEMBLY_NAMES, DocumentationGateway, tool_specs
from ai_inspector.codex_runtime.mcp_bridge import explicit_types
from ai_inspector.codex_runtime.pilot import Journal
from ai_inspector.codex_runtime.policy import LIVE_FLAG, PilotSettings
from ai_inspector.codex_runtime.progress import describe
from tests.test_codex_documentation_tools import PRINCIPAL, Host, call
from tests.test_codex_mcp_schema_types import untyped_nodes

PARTS = {"frame": "Frame", "door": "Door", "spindle": "Spindle cover"}


class AppearanceHost(Host):
    """The documentation host with the appearance store, as _DocumentationAgentHost has it."""

    def __init__(self, root):
        super().__init__()
        self.store = AssemblyAppearanceStore(root)

    def assembly_appearance(self, number):
        return self.store.read(number)

    def assembly_parts(self, number):
        return dict(PARTS)

    def write_assembly_appearance(self, number, whole, parts):
        return self.store.write(number, whole, parts, part_numbers=PARTS, by="sage")


@pytest.fixture(autouse=True)
def no_public_research(monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "0")


def gateway(tmp_path, workspace="documentation"):
    return DocumentationGateway(AppearanceHost(tmp_path), PRINCIPAL, {"assemblyNumber": "tricycle",
                                "documentType": None}, turn_id="turn", workspace=workspace)


def test_the_assembly_tab_has_only_the_assembly_library_and_appearance_tools_typed_and_closed():
    specs = tool_specs(workspace="assembly")
    assert tuple(spec["name"] for spec in specs) == ASSEMBLY_NAMES
    for spec in specs:
        typed = explicit_types(spec["input_schema"])
        Draft202012Validator.check_schema(typed)
        assert untyped_nodes(typed) == [] and spec["input_schema"]["additionalProperties"] is False, spec["name"]
    assert [spec["name"] for spec in specs if not spec.get("read_only", True)] == [
        "open_library_machine", "set_assembly_appearance", "set_assembly_scene", "place_assembly_signs",
        "remove_assembly_signs", "place_assembly_dimensions", "remove_assembly_dimensions", "show_assembly_parts",
        "move_parts_manual_parts"]
    assert "3D view" in next(spec for spec in specs if spec["name"] == "open_library_machine")["description"]
    documentation = [spec["name"] for spec in tool_specs()]
    assert "list_appearances" in documentation and "set_assembly_appearance" in documentation
    assert "inspect_assembly" not in documentation


def test_sage_lists_finishes_and_parts_and_sets_them_on_the_server(tmp_path):
    reader = gateway(tmp_path)
    listed = call(reader, "list_appearances", {"query": "glass"})
    assert listed["ok"] and {row["appearanceId"] for row in listed["data"]["finishes"]} == {
        "glass-clear", "glass-frosted"}
    assert listed["data"]["parts"][1] == {"part": "door", "name": "Door"}
    # Lights glow only in the Facility 3D view: the Assembly list leaves them out, and a set refuses one.
    everything = call(reader, "list_appearances", {})["data"]["finishes"]
    assert everything and not any(row["category"] == "lights" for row in everything)
    assert call(reader, "list_appearances", {"query": "stack light"})["data"]["finishes"] == []
    refused = call(reader, "set_assembly_appearance", {"assignments": [
        {"target": "whole", "appearanceId": "light-stack-green"}]})
    assert not refused["ok"] and "Lights finish" in str(refused), refused
    assert listed["data"]["now"] == {"whole": None, "parts": {}} and "line drawings" in listed["data"]["note"]
    result = call(reader, "set_assembly_appearance", {"assignments": [
        {"target": "whole", "appearanceId": "paint-machine-gray"},
        {"target": "parts", "parts": ["door"], "appearanceId": "glass-clear"},
        {"target": "parts", "parts": ["spindle", "frame"], "appearanceId": "paint-gloss-red", "color": "#1D4F91"}]})
    assert result["ok"], result
    stored = reader.host.store.read("tricycle")
    assert stored["whole"] == {"appearanceId": "paint-machine-gray"} and stored["by"] == "sage"
    assert stored["parts"]["frame"] == {"appearanceId": "paint-gloss-red", "color": "#1d4f91"}
    assert reader.appearance_changes == ["tricycle"]
    removed = call(reader, "set_assembly_appearance", {"assignments": [
        {"target": "parts", "parts": ["frame"], "remove": True}]})
    assert removed["ok"] and set(reader.host.store.read("tricycle")["parts"]) == {"door", "spindle"}
    assert call(reader, "set_assembly_appearance", {"clear": True})["ok"]
    assert reader.host.store.read("tricycle")["whole"] is None and reader.appearance_changes == ["tricycle"]


@pytest.mark.parametrize("arguments, code", [
    ({}, "appearance_nothing_to_set"),
    ({"assignments": [{"target": "whole"}]}, "appearance_required"),
    ({"assignments": [{"target": "parts", "parts": ["wheel"], "appearanceId": "steel-brushed"}]},
     "appearance_unknown_parts"),
    ({"assignments": [{"target": "parts", "appearanceId": "steel-brushed"}]}, "appearance_unknown_parts"),
    ({"assignments": [{"target": "whole", "appearanceId": "gold-leaf"}]}, "appearance_invalid"),
    ({"assignments": [{"target": "whole", "appearanceId": "steel-brushed", "color": "blue"}]},
     "codex_tool_arguments_invalid"),
])
def test_a_wrong_assignment_is_refused_and_nothing_is_written(tmp_path, arguments, code):
    reader = gateway(tmp_path)
    result = call(reader, "set_assembly_appearance", arguments)
    assert result["error"]["code"] == code
    assert reader.host.store.read("tricycle")["whole"] is None and reader.appearance_changes == []


def test_the_assembly_tab_reads_the_assembly_and_refuses_documentation_tools(tmp_path):
    reader = gateway(tmp_path, workspace="assembly")
    read = call(reader, "inspect_assembly", {})
    assert read["ok"] and read["data"]["name"] == "Tricycle Assembly" and read["data"]["finishes"]["whole"] is None
    assert call(reader, "build_inspection_sheet", {})["error"]["code"] == "codex_tool_denied"


def test_the_steps_name_the_appearance_work():
    assert describe("list_appearances", {})["running"] == "Reading the finishes and the machine's parts"
    assert describe("set_assembly_appearance", {"assignments": [{}, {}]})["done"] == "Updated the machine's finishes"
    assert describe("set_assembly_appearance", {"clear": True})["done"] == "Updated the machine's finishes (cleared)"
    assert describe("inspect_assembly", {})["done"] == "Read the assembly"


def test_an_assembly_turn_uses_its_instructions_and_reports_the_appearance_change(tmp_path, monkeypatch):
    monkeypatch.setenv(LIVE_FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "synthetic-never-sent")
    state = {"statuses": []}

    @asynccontextmanager
    async def bridge(reader):
        state["gateway"] = reader
        try:
            yield "http://127.0.0.1:9/mcp", "test-capability"
        finally:
            reader.closed = True

    class Transport:
        def __init__(self, binary, root, env, config):
            state["tools"] = config["mcp_servers"]["inspectorpro"]["enabled_tools"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def inspect(self, **kwargs):
            assert "in the Assembly tab" in kwargs["instructions"]
            assert "Workflows > Documentation" not in kwargs["instructions"]
            kwargs["on_thread"]("thread-test")
            await kwargs["status_sink"]("codex_inspecting")
            reader = state["gateway"]
            assert (await reader.call("inspect_assembly", {}))["ok"]
            assert (await reader.call("set_assembly_appearance", {"assignments": [
                {"target": "whole", "appearanceId": "paint-safety-yellow"}]}))["ok"]
            return "Painted the tricycle safety yellow."

    async def status(phase):
        state["statuses"].append(phase)

    monkeypatch.setattr(documentation_pilot, "serve_gateway", bridge)
    request = SimpleNamespace(agent_session_id="session", session_id=None, client_turn_id="turn",
        conversation_id="conversation", message="Paint it safety yellow", context=None, inspection_context={})
    fake = AppearanceHost(tmp_path / "appearances")
    host = SimpleNamespace(**{name: getattr(fake, name) for name in (
        "library", "assembly", "state", "bom", "assembly_appearance", "assembly_parts",
        "write_assembly_appearance")}, resolve_principal=lambda _: PRINCIPAL)
    settings = PilotSettings(Path("unused"), tmp_path / "pilot", "test-model")
    result = asyncio.run(inspect_documentation(request, host, None, {"assembly_number": "tricycle"},
        settings=settings, transport_factory=Transport, status_sink=status, workspace="assembly"))
    assert state["tools"] == list(ASSEMBLY_NAMES)
    assert "codex_assembly" in state["statuses"] and "codex_documentation" not in state["statuses"]
    receipt = result["codex_documentation"]
    assert receipt["workspace"] == "assembly" and receipt["appearanceChanges"] == ["tricycle"]
    assert result["tool_calls"] == [] and receipt["checkedDocumentation"] is True
    assert fake.store.read("tricycle")["whole"] == {"appearanceId": "paint-safety-yellow"}
    with Journal(settings.root).db() as db:
        assert db.execute("SELECT status FROM turns").fetchone()[0] == "completed"
