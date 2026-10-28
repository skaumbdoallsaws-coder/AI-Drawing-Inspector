"""Sage on Codex in Documentation: tools, readiness, limits and the turn. No credentials or inference."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import httpx
from jsonschema import Draft202012Validator
import pytest

from ai_inspector.codex_runtime import documentation_pilot
from ai_inspector.codex_runtime.documentation_pilot import documentation_binding, inspect_documentation
from ai_inspector.codex_runtime.documentation_tools import (
    GUIDE, MAX_EDITS, NAMES, WORKFLOWS, DocumentationGateway, said, tool_specs,
)
from ai_inspector.codex_runtime.mcp_bridge import explicit_types, make_application
from ai_inspector.codex_runtime.pilot import Journal
from ai_inspector.codex_runtime.policy import LIVE_FLAG, PilotError, PilotSettings
from ai_inspector.documentation.agent_tools import DOCUMENTATION_AGENT_TOOL_SPECS
from ai_inspector.documentation.registry import DOCUMENT_TYPE_REGISTRY
from tests.test_codex_mcp_schema_types import untyped_nodes

PRINCIPAL = SimpleNamespace(tenant_id="tenant", principal_id="user", roles=(), allowed_site_ids=())
PUBLISH = {"approval_mode": "approve_trusted_ready_candidates", "layout_mode": "generate_baseline_if_missing",
           "open_pdf": True}


def parts_state(publishable=False, ready=3, conflicts=0, unassigned=0, coverage=100.0, trusted=True):
    return {"ok": True, "data": {
        "structure": {"approvedSections": 3 if publishable else 0, "publishable": publishable, "sourceCurrent": True,
                      "coveragePercent": 100.0 if publishable else 0.0, "auditFindings": 0 if publishable else 2},
        "proposal": {"candidateCount": 3, "readyCount": ready, "conflictCount": conflicts,
                     "unassignedCount": unassigned, "coveragePercent": coverage, "evidence": ["process_map"],
                     "trustedForPublish": {"ok": True} if trusted else
                     {"ok": False, "reason": "these sections come from library_manual_profile evidence"}}}}


class Host:
    """The app's documentation reads for one library, as _DocumentationAgentHost returns them."""

    def __init__(self, parts=None):
        self.revision = "rev-1"
        self.reads = []
        self.states = {
            "illustrated_parts_manual": parts or parts_state(),
            "operations_and_maintenance_manual": {"ok": False, "code": "operations_manual_validation",
                "message": "publication nomenclature is bound to a different assembly"},
            "product_specification_sheet": {"ok": True, "data": {"releaseGate": {"status": "REVIEW_READY",
                "findings": []}}},
            "work_instructions": {"ok": False, "code": "work_instruction_validation",
                "message": "a planning-ready Assembly Knowledge package is required"},
            "inspection_sheet": {"ok": True, "data": {
                "summary": {"parts": 2, "characteristics": 25, "openFields": 3},
                "openFields": [{"name": "header.lot", "label": "Lot or serial number", "part": None},
                               {"name": "part.100006.general_tolerance", "label": "100006: general tolerance",
                                "part": "100006"},
                               {"name": "part.100006.drawing_revision", "label": "100006: drawing revision",
                                "part": "100006"}],
                "built": None, "lastReturn": None}},
        }
        self.builds = []
        self.provided = []

    def library(self):
        return [{"assemblyNumber": "tricycle", "name": "Tricycle Assembly"},
                {"assemblyNumber": "100001", "name": "Four Cylinder Engine Assembly"}]

    def assembly(self, number):
        if number != "tricycle":
            raise LookupError(number)
        return {"assemblyNumber": "tricycle", "name": "Tricycle Assembly", "sourceRevision": self.revision,
                "partInstances": 26, "partDefinitions": 19, "subassemblies": 0,
                "partNumbers": {"withPartNumber": 0, "notSpecified": 26}}

    def state(self, number, document_type, detail=False):
        self.reads.append((document_type, detail))
        return deepcopy(self.states[document_type])

    def bom(self, number, section_id=None):
        rows = [{"item": index + 1, "partNumber": "Not specified", "description": f"part {index}", "quantity": 2}
                for index in range(50)]
        return {"scope": section_id or "whole assembly", "rows": rows}

    def build_inspection_sheet(self, number):
        self.builds.append(number)
        sheet = self.states["inspection_sheet"]["data"]
        return {"summary": sheet["summary"], "openFields": sheet["openFields"],
                "built": {"pages": 5, "pdfUrl": f"/api/inspection-sheet/{number}/documents/{'a' * 64}/pdf"}}

    def provide_inspection_sheet_values(self, number, values, quote):
        self.provided.append((values, quote))
        names = [item["name"] for item in values]
        sheet = self.states["inspection_sheet"]["data"]
        sheet["openFields"] = [field for field in sheet["openFields"] if field["name"] not in names]
        return {"set": names, "refused": [], "openFieldCount": len(sheet["openFields"]),
                "openFields": sheet["openFields"]}


@pytest.fixture(autouse=True)
def no_public_research(monkeypatch):
    """The exact tool set; public research joins it only behind its flag (tested below)."""
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "0")


def gateway(host=None, number="tricycle", **kwargs):
    return DocumentationGateway(host or Host(), PRINCIPAL, {"assemblyNumber": number, "documentType": None},
                                turn_id="turn", **kwargs)


def call(reader, name, arguments):
    return asyncio.run(reader.call(name, arguments))


def test_the_tool_set_is_exact_typed_and_closed():
    specs = tool_specs()
    assert tuple(spec["name"] for spec in specs) == NAMES
    for spec in specs:
        schema = spec["input_schema"]
        assert schema["type"] == "object" and schema["additionalProperties"] is False, spec["name"]
        typed = explicit_types(schema)
        Draft202012Validator.check_schema(typed)
        assert untyped_nodes(typed) == [], spec["name"]
    assert {spec["name"] for spec in specs if spec.get("read_only", True)} == {
        "inspect_documentation_context", "inspect_documentation_type", "inspect_parts_manual_bom",
        "find_library_machines", "list_appearances", "list_part_faces", "list_signs_and_scenes",
        "read_document_pages"}


def test_public_research_joins_the_tools_behind_its_flag(monkeypatch):
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "1")
    names = [spec["name"] for spec in gateway().specs]
    assert names == list(NAMES) + ["search_public_sources", "read_public_source"]


def test_every_document_type_has_a_guide_and_every_workflow_is_a_browser_tool():
    assert set(GUIDE) == set(DOCUMENT_TYPE_REGISTRY)
    assert set(WORKFLOWS) == set(DOCUMENTATION_AGENT_TOOL_SPECS)
    for name, (document_type, kind) in WORKFLOWS.items():
        assert document_type in DOCUMENT_TYPE_REGISTRY and kind in ("proposal", "draft", "publish", "edit"), name
    for document_type, guide in GUIDE.items():
        assert guide["purpose"] and guide["outputs"], document_type
        assert all(who in ("user", "app", "user or app", "user (inspector)", "user (approves)")
                   for _, _, who in guide["needs"]), \
            document_type
    json.dumps(tool_specs()).encode("ascii")


def test_context_gives_each_types_needs_and_the_apps_own_readiness():
    result = call(gateway(), "inspect_documentation_context", {})
    assert result["ok"] and result["data"]["readOnly"]
    data = result["data"]
    assert data["assembly"]["partNumbers"] == {"withPartNumber": 0, "notSpecified": 26}
    assert "sourceRevision" not in data["assembly"]
    types = {entry["documentType"]: entry for entry in data["documentTypes"]}
    assert set(types) == set(DOCUMENT_TYPE_REGISTRY)
    parts = types["illustrated_parts_manual"]
    assert {need["input"] for need in parts["needs"]} >= {"part_numbers", "grouping_evidence", "approved_structure"}
    assert parts["forThisAssembly"]["canBuild"] and parts["forThisAssembly"]["publishWith"] == \
        "approve_trusted_ready_candidates"
    operations = types["operations_and_maintenance_manual"]["forThisAssembly"]
    assert operations == {"canBuild": False, "appCode": "operations_manual_validation",
                          "blockedBy": "publication nomenclature is bound to a different assembly"}
    assert types["product_specification_sheet"]["forThisAssembly"]["releaseGate"] == "REVIEW_READY"
    sheet = types["inspection_sheet"]
    assert sheet["workflows"] == ["build_inspection_sheet", "provide_inspection_sheet_values"]
    assert sheet["forThisAssembly"]["canBuild"] is True
    assert "open fields" in sheet["forThisAssembly"]["missingInformation"]
    assert sheet["forThisAssembly"]["summary"]["openFields"] == 3
    assert [row["assemblyNumber"] for row in data["otherAssemblies"]] == ["100001"]


def test_each_type_is_read_once_per_turn():
    host = Host()
    reader = gateway(host, max_calls=10)
    call(reader, "inspect_documentation_context", {})
    call(reader, "inspect_documentation_context", {})
    call(reader, "run_documentation_workflow", {"workflow": "generate_specification_sheet_draft"})
    assert sorted(host.reads) == sorted((name, False) for name, item in DOCUMENT_TYPE_REGISTRY.items()
                                        if item["status"] != "planned")


@pytest.mark.parametrize("parts,workflow,arguments,blocked", [
    (parts_state(publishable=True), "generate_and_publish_parts_manual",
     {**PUBLISH, "approval_mode": "use_approved_structure"}, None),
    (parts_state(), "generate_and_publish_parts_manual", PUBLISH, None),
    (parts_state(), "generate_and_publish_parts_manual", {**PUBLISH, "approval_mode": "use_approved_structure"},
     "No structure is approved yet"),
    (parts_state(trusted=False), "generate_and_publish_parts_manual", PUBLISH,
     "library_manual_profile evidence. Build the draft first"),
    (parts_state(trusted=False), "generate_parts_manual_draft", {}, None),
    (parts_state(conflicts=1), "generate_parts_manual_draft", {}, "1 conflicts"),
    (parts_state(coverage=92.0, unassigned=2), "generate_parts_manual_draft", {}, "92.0% of serviceable parts"),
    (parts_state(ready=0), "generate_parts_manual_draft", {}, "not complete"),
    (parts_state(), "edit_parts_manual_composition", None, "no figures to edit"),
    (parts_state(publishable=True), "edit_parts_manual_composition", None, None),
    (parts_state(ready=0), "propose_parts_manual_structure", {}, None),
])
def test_parts_manual_workflows_follow_the_browsers_own_rules(parts, workflow, arguments, blocked):
    request = ({"workflow": workflow, "edits": [{"operation": "undo"}]} if arguments is None
               else {"workflow": workflow, **({"arguments": arguments} if arguments else {})})
    reader = gateway(Host(parts))
    result = call(reader, "run_documentation_workflow", request)
    if blocked:
        assert result["error"]["code"] == "documentation_workflow_blocked" and blocked in result["error"]["message"]
        assert reader.queued == []
    else:
        assert result["ok"] and result["data"]["runsAfterReply"], result
        assert reader.queued[0]["name"] == workflow


def test_review_only_types_refuse_with_the_apps_reason():
    reader = gateway(max_calls=10)
    result = call(reader, "run_documentation_workflow", {"workflow": "generate_work_instructions_draft"})
    assert result["error"]["code"] == "documentation_workflow_blocked"
    assert "a planning-ready Assembly Knowledge package is required" in result["error"]["message"]
    detail = call(reader, "inspect_documentation_type", {"documentType": "inspection_sheet"})
    assert detail["ok"] and detail["data"]["canBuild"] is True
    assert [field["name"] for field in detail["data"]["state"]["openFields"]][0] == "header.lot"
    assert not any(kind == "inspection_sheet" for kind, _ in WORKFLOWS.values())  # it has its own tools


def test_the_inspection_sheet_builds_during_the_turn_with_its_open_fields():
    host = Host()
    reader = gateway(host, max_calls=10)
    result = call(reader, "build_inspection_sheet", {})
    assert result["ok"], result
    data = result["data"]
    assert data["built"] and data["pages"] == 5 and data["pdfUrl"].endswith("/pdf")
    assert [field["name"] for field in data["openFields"]][:2] == ["header.lot", "part.100006.general_tolerance"]
    assert host.builds == ["tricycle"]
    assert reader.built == [{"documentType": "inspection_sheet", "assemblyNumber": "tricycle",
                             "pdfUrl": data["pdfUrl"], "pages": 5, "openFields": 3, "characteristics": 25}]
    host.states["inspection_sheet"] = {"ok": False, "code": "inspection_sheet_validation",
                                       "message": "the parts catalog is unreadable"}
    refused = call(gateway(host), "build_inspection_sheet", {})
    assert refused["error"]["code"] == "documentation_workflow_blocked"
    assert "the parts catalog is unreadable" in refused["error"]["message"]
    assert call(gateway(number=None), "build_inspection_sheet", {})["error"]["code"] == \
        "documentation_assembly_required"


def test_only_values_the_user_said_are_recorded():
    host = Host()
    message = "The piston's general tolerance is +/- 0.05 mm and the lot is LOT-0425."
    reader = gateway(host, max_calls=10, user_message=message)
    result = call(reader, "provide_inspection_sheet_values", {"values": [
        {"name": "part.100006.general_tolerance", "value": "\u00b10.05"},
        {"name": "header.lot", "value": "lot-0425"},
        {"name": "part.100006.drawing_revision", "value": "B"},  # a guess: not in the message
    ]})
    assert result["ok"], result
    data = result["data"]
    assert data["recorded"] == ["part.100006.general_tolerance", "header.lot"]
    assert data["refused"] == [{"name": "part.100006.drawing_revision",
                                "reason": "the user did not say this value in this message"}]
    assert data["openFieldCount"] == 1
    values, quote = host.provided[0]
    assert [item["name"] for item in values] == ["part.100006.general_tolerance", "header.lot"]
    assert quote == message and reader.provided == data["recorded"]

    nothing = call(gateway(host, user_message="build it"), "provide_inspection_sheet_values",
                   {"values": [{"name": "header.customer", "value": "Acme"}]})
    assert nothing["error"]["code"] == "documentation_value_not_stated"
    assert len(host.provided) == 1
    bad = call(gateway(host, user_message="Acme"), "provide_inspection_sheet_values",
               {"values": [{"name": "../x", "value": "Acme"}]})
    assert bad["error"]["code"] == "codex_tool_arguments_invalid"


@pytest.mark.parametrize("request_,path", [
    ({"workflow": "publish_specification_sheet", "arguments": {"open_pdf": True}}, "/"),
    ({"workflow": "publish_specification_sheet", "arguments": {"open_pdf": True, "open_docx": False,
                                                              "approval_mode": "use_approved_structure"}}, "/"),
    ({"workflow": "generate_parts_manual_draft", "edits": [{"operation": "undo"}]}, "/edits"),
    ({"workflow": "edit_parts_manual_composition", "edits": [{"operation": "undo"}], "arguments": {}}, "/arguments"),
])
def test_workflow_arguments_are_checked_against_the_browser_tools_schema(request_, path):
    result = call(gateway(), "run_documentation_workflow", request_)
    assert result["error"]["code"] == "codex_tool_arguments_invalid"
    assert result["error"]["details"]["findings"][0]["path"] == path


def test_tool_arguments_outside_the_schema_are_refused():
    reader = gateway(max_calls=10)
    for name, arguments in [("inspect_documentation_context", {"assemblyNumber": "100001"}),
                            ("inspect_documentation_type", {"documentType": "brochure"}),
                            ("run_documentation_workflow", {"workflow": "delete_manual"}),
                            ("inspect_parts_manual_bom", {"pageSize": 500}),
                            ("write_file", {})]:
        result = call(reader, name, arguments)
        assert not result["ok"], name
    assert [receipt["tool"] for receipt in reader.receipts][-1] == "denied"


def test_one_workflow_per_reply_or_up_to_five_edits():
    reader = gateway(Host(parts_state(publishable=True)), max_calls=10)
    edit = {"workflow": "edit_parts_manual_composition", "edits": [{"operation": "undo"}] * 3}
    assert call(reader, "run_documentation_workflow", edit)["ok"]
    assert call(reader, "run_documentation_workflow", edit)["error"]["code"] == "documentation_too_many_edits"
    other = call(reader, "run_documentation_workflow", {"workflow": "generate_parts_manual_draft"})
    assert other["error"]["code"] == "documentation_workflow_already_queued"
    assert len(reader.queued) == 3
    six = {"workflow": "edit_parts_manual_composition", "edits": [{"operation": "redo"}] * (MAX_EDITS + 1)}
    assert call(gateway(Host(parts_state(publishable=True))), "run_documentation_workflow", six)["error"]["code"] \
        == "codex_tool_arguments_invalid"


def test_without_an_assembly_sage_can_still_list_types_and_the_library():
    reader = gateway(number=None, max_calls=10)
    context = call(reader, "inspect_documentation_context", {})
    assert context["ok"] and context["data"]["assembly"] is None
    assert len(context["data"]["otherAssemblies"]) == 2
    assert "forThisAssembly" not in context["data"]["documentTypes"][0]
    for name, arguments in [("inspect_documentation_type", {"documentType": "illustrated_parts_manual"}),
                            ("inspect_parts_manual_bom", {}),
                            ("run_documentation_workflow", {"workflow": "generate_parts_manual_draft"})]:
        assert call(reader, name, arguments)["error"]["code"] == "documentation_assembly_required", name


def test_an_assembly_outside_the_library_or_a_changed_one_ends_the_turn():
    with pytest.raises(PilotError) as caught:
        gateway(number="100010")
    assert caught.value.code == "documentation_assembly_unavailable"
    host = Host()
    reader = gateway(host)
    host.revision = "rev-2"
    result = call(reader, "inspect_documentation_context", {})
    assert result["error"]["code"] == "documentation_assembly_changed"


def test_bill_of_materials_pages_and_budget_receipts():
    reader = gateway(max_calls=2)
    page = call(reader, "inspect_parts_manual_bom", {"offset": 40, "pageSize": 20})["data"]
    assert page["uniqueItems"] == 50 and page["partInstances"] == 100 and len(page["rows"]) == 10
    assert page["more"] is False and "Not specified" in page["partNumberNote"]
    call(reader, "inspect_parts_manual_bom", {})
    spent = call(reader, "inspect_documentation_context", {})
    assert spent["error"]["code"] == "codex_tool_budget_exhausted"
    assert [receipt["ok"] for receipt in reader.receipts] == [True, True, False]
    assert all(len(receipt["argumentHash"]) == 64 for receipt in reader.receipts)


def test_page_text_is_read_with_the_users_edits_and_changed_through_the_host():
    page = {"pageId": "page-7", "pageNumber": 7, "title": "Pre-Use Inspection", "documentationComposition": {
        "pageElementOverrides": {"checks.r0.c1": {"text": "Edited by the user"}}},
        "layoutBlocks": [
            {"blockId": "intro", "blockType": "paragraph", "text": "Check the lift before use."},
            {"blockId": "checks", "blockType": "table", "columns": ["Item", "Check"],
             "rows": [{"cells": ["Hoses", "No leaks"]}]},
            {"blockId": "steps", "blockType": "list", "items": [{"label": "Step 1", "text": "Lower the arms"}]},
            {"blockId": "fig", "blockType": "cad_figure", "caption": "Figure 3"},
            {"blockId": "toc", "blockType": "contents_list", "entries": []}]}
    other = {**page, "pageId": "page-8", "pageNumber": 8}

    class TextHost(Host):
        def __init__(self):
            super().__init__()
            self.edits = []

        def document_pages(self, number, document_type):
            self.reads.append(("pages", number, document_type))
            return [page, other]

        def edit_document_text(self, number, document_type, edits):
            self.edits.append((number, document_type, edits))
            return [{"pageId": row["pageId"], "targetId": row["targetId"]} for row in edits]

    host = TextHost()
    reader = gateway(host)
    read = call(reader, "read_document_pages", {"documentType": "work_instructions", "fromPage": 7, "pageCount": 1})
    assert read["ok"], read
    shown = read["data"]["pages"]
    assert [row["pageId"] for row in shown] == ["page-7"] and read["data"]["pageCount"] == 2
    blocks = {block["id"]: block for block in shown[0]["blocks"]}
    assert "toc" not in blocks
    assert blocks["intro"]["text"] == "Check the lift before use."
    assert blocks["checks"]["rows"][0] == [{"id": "checks.r0.c0", "text": "Hoses"},
                                           {"id": "checks.r0.c1", "text": "Edited by the user"}]
    assert blocks["steps"]["items"] == [{"id": "steps.i0", "label": "Step 1", "text": "Lower the arms"}]
    assert blocks["fig"] == {"id": "fig", "type": "caption", "text": "Figure 3"}
    edits = [{"pageId": "page-7", "targetId": "checks.r0.c1", "text": "No leaks at the fittings"}]
    edited = call(reader, "edit_document_text", {"documentType": "work_instructions", "edits": edits})
    assert edited["ok"], edited
    assert host.edits == [("tricycle", "work_instructions", edits)]
    assert reader.text_changes == ["work_instructions"]
    refused = call(reader, "edit_document_text", {"documentType": "product_specification_sheet", "edits": edits})
    assert not refused["ok"] and len(host.edits) == 1


def test_binding_comes_from_the_chat_request_not_tool_arguments():
    request = SimpleNamespace(inspection_context={"attachments": {"documentation": {
        "active_document_type": "work_instructions"}}}, context=None)
    assert documentation_binding(request, {"assembly_number": "MMLE-50D"}) == {
        "assemblyNumber": "MMLE-50D", "documentType": "work_instructions"}
    assert documentation_binding(request, {})["assemblyNumber"] is None
    with pytest.raises(PilotError):
        documentation_binding(request, {"assembly_number": "../etc"})
    other = SimpleNamespace(inspection_context={"attachments": {"documentation": {"document_type": "brochure"}}},
                            context=None)
    assert documentation_binding(other, {"assembly_number": "tricycle"})["documentType"] is None


def test_mcp_serves_the_documentation_tools_with_their_own_instructions():
    pytest.importorskip("mcp")
    reader = gateway()
    app, manager = make_application(reader, "secret", "127.0.0.1:7654")

    async def exercise():
        async with manager.run():
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 1234))
            async with httpx.AsyncClient(transport=transport, base_url="http://127.0.0.1:7654") as client:
                headers = {"Authorization": "Bearer secret", "Accept": "application/json, text/event-stream",
                           "MCP-Protocol-Version": "2025-11-25"}
                body = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
                    "protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}}}
                result = await client.post("/mcp", json=body, headers=headers)
                assert "loaded assembly's documentation" in result.json()["result"]["instructions"]
                body = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
                result = await client.post("/mcp", json=body, headers=headers)
                assert [tool["name"] for tool in result.json()["result"]["tools"]] == list(NAMES)
                body.update(method="tools/call", params={"name": "inspect_documentation_context", "arguments": {}})
                result = await client.post("/mcp", json=body, headers=headers)
                assert result.json()["result"]["structuredContent"]["ok"], result.text
    asyncio.run(exercise())


@pytest.mark.parametrize("outcome", ["queued", "read_only", "refused", "built"])
def test_a_turn_returns_the_queued_workflow_with_a_receipt_and_replays(tmp_path, monkeypatch, outcome):
    monkeypatch.setenv(LIVE_FLAG, "1")
    monkeypatch.setenv("INSPECTORPRO_CODEX_API_KEY", "synthetic-never-sent")
    state = {"starts": 0, "statuses": []}

    @asynccontextmanager
    async def bridge(reader):
        state["gateway"] = reader
        try:
            yield "http://127.0.0.1:9/mcp", "test-capability"
        finally:
            reader.closed = True

    class Transport:
        def __init__(self, binary, root, env, config):
            state["starts"] += 1
            state["tools"] = config["mcp_servers"]["inspectorpro"]["enabled_tools"]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_):
            pass

        async def inspect(self, **kwargs):
            assert "Workflows > Documentation" in kwargs["instructions"]
            kwargs["on_thread"]("thread-test")
            await kwargs["status_sink"]("codex_inspecting")
            reader = state["gateway"]
            assert (await reader.call("inspect_documentation_context", {}))["ok"]
            if outcome == "queued":
                queued = await reader.call("run_documentation_workflow", {
                    "workflow": "generate_and_publish_parts_manual", "arguments": PUBLISH})
                assert queued["ok"], queued
            if outcome == "refused":
                refused = await reader.call("run_documentation_workflow", {"workflow": "publish_work_instructions",
                    "arguments": {"open_pdf": True, "open_docx": False}})
                assert refused["error"]["code"] == "documentation_workflow_blocked"
            if outcome == "built":
                assert (await reader.call("build_inspection_sheet", {}))["ok"]
            return "Publishing the tricycle parts manual now."

    async def status(phase):
        state["statuses"].append(phase)

    monkeypatch.setattr(documentation_pilot, "serve_gateway", bridge)
    request = SimpleNamespace(agent_session_id="session", session_id=None, client_turn_id="turn",
        conversation_id="conversation", message="Publish the parts manual", context=None,
        inspection_context={"attachments": {"documentation": {"active_document_type": "illustrated_parts_manual"}}})
    fake = Host()
    host = SimpleNamespace(**{name: getattr(fake, name) for name in (
        "library", "assembly", "state", "bom", "build_inspection_sheet", "provide_inspection_sheet_values")},
        resolve_principal=lambda _: PRINCIPAL)
    settings = PilotSettings(Path("unused"), tmp_path / "pilot", "test-model")
    guarded = []

    def guard(calls):
        guarded.append(calls)
        return calls, []

    def invoke():
        return asyncio.run(inspect_documentation(request, host, None, {"assembly_number": "tricycle"},
            settings=settings, transport_factory=Transport, status_sink=status, guard_tool_calls=guard))

    result = invoke()
    assert state["tools"] == list(NAMES)
    assert "codex_inspecting" not in state["statuses"] and "codex_documentation" in state["statuses"]
    assert result["tool_source"] == "codex_documentation"
    assert result["response"] == "Publishing the tricycle parts manual now."
    receipt = result["codex_documentation"]
    assert receipt["assemblyNumber"] == "tricycle" and receipt["documentType"] == "illustrated_parts_manual"
    assert receipt["checkedDocumentation"] is True and receipt["apiFallback"] is False
    if outcome == "queued":
        assert result["tool_calls"] == [{"name": "generate_and_publish_parts_manual", "args": PUBLISH}]
        assert receipt["queuedWorkflows"] == ["generate_and_publish_parts_manual"] and len(guarded) == 1
    else:
        assert result["tool_calls"] == [] and receipt["queuedWorkflows"] == [] and guarded == []
    assert receipt["builtDocuments"] == ([{"documentType": "inspection_sheet", "assemblyNumber": "tricycle",
        "pdfUrl": f"/api/inspection-sheet/tricycle/documents/{'a' * 64}/pdf", "pages": 5, "openFields": 3,
        "characteristics": 25}] if outcome == "built" else [])
    assert receipt["providedValues"] == []
    assert result.get("content_blocks", []) == ([{"type": "file", "fileName": "tricycle inspection sheet.pdf",
        "url": f"/api/inspection-sheet/tricycle/documents/{'a' * 64}/pdf", "mimeType": "application/pdf",
        "detail": "5 pages, 25 characteristics, 3 open fields"}] if outcome == "built" else [])
    assert state["gateway"].closed
    assert invoke() == result and state["starts"] == 1
    with Journal(settings.root).db() as db:
        assert db.execute("SELECT status FROM turns").fetchone()[0] == "completed"


@pytest.mark.parametrize("value, expected", [
    ("C", True), ("±0.05", True), ("0.05", True), ("+/- 0.05 mm", True), ("lot-0425", True),
    ("Ø30.02", True), ("30.02", True),
    ("5", False), ("30.0", False), ("B", False), ("e", False), ("", False),
])
def test_a_value_counts_as_said_only_as_a_whole_token(value, expected):
    message = "Piston: general tolerance +/- 0.05 mm, revision C, lot LOT-0425, bore Ø30.02"
    assert said(value, message) is expected
