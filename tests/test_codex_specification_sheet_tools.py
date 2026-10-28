"""Sage's specification-sheet tools (docs/specification-sheet-slots-plan.md, SS4), through the gateway and the real
server host on the engine 100001: names approved by the user, values only from the user's words or a source read in
the turn, drafts without new numbers, and the export. No credentials or inference."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway, approval_said
from tests.test_specification_sheet_slots import _pdf_text, _render

PRINCIPAL = SimpleNamespace(tenant_id="tenant", principal_id="user", roles=(), allowed_site_ids=())
SPEC = "product_specification_sheet"


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "sheets")
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "0")
    test_client = TestClient(server.app)
    test_client.post("/api/specification-sheet/100001/generate?rebaseline=true")
    return test_client


def turn(message):
    return DocumentationGateway(server._DOCUMENTATION_AGENT_HOST, PRINCIPAL,
                                {"assemblyNumber": "100001", "documentType": SPEC},
                                turn_id="turn", max_calls=24, user_message=message)


def call(gateway, name, arguments):
    return asyncio.run(gateway.call(name, arguments))


def slots(client):
    return client.get("/api/specification-sheet/100001/slots").json()


def test_approval_needs_the_users_own_yes():
    assert approval_said("Yes, approve them.") and approval_said("Looks good, go ahead")
    assert not approval_said("Don't approve yet") and not approval_said("What would you put on it?")


def test_sage_proposes_the_names_the_user_approves_and_records_only_what_the_user_said(client):
    first = turn("What would the specification sheet for this engine show?")
    read = call(first, "inspect_documentation_type", {"documentType": SPEC})
    sheet = read["data"]["state"]["specificationSheet"]
    assert not sheet["hasProfile"] and sheet["slots"]["spec.weight.value"]["source"] == "cad"
    assert sheet["slots"]["tagline"]["open"] and not sheet["export"]["captureCurrent"]
    proposed = call(first, "propose_specification_template", {
        "type": "piston_engine", "typeLabel": "Piston engine", "rows": [
            {"label": "Cylinders", "hint": "number of cylinders"}, {"label": "Displacement", "unit": "L"},
            {"label": "Overall dimensions (W x D x H)", "cad": "dimensions"}]})
    assert proposed["ok"], proposed
    assert [row["key"] for row in proposed["data"]["proposed"]] == ["cylinders", "displacement", "overall_dimensions"]
    pending = slots(client)
    assert pending["sheet"]["type"]["proposal"] and [row["key"] for row in pending["sheet"]["rows"]] == [
        "overall_dimensions", "weight"]  # not used until approved
    refused = call(first, "approve_specification_template", {"type": "piston_engine"})
    assert refused["error"]["code"] == "specification_approval_not_stated"

    second = turn("Yes, approve them. It has 4 cylinders and displaces 1.6 L.")
    assert call(second, "approve_specification_template", {"type": "piston_engine"})["ok"]
    values = call(second, "provide_document_values", {"documentType": SPEC, "values": [
        {"slot": "spec.cylinders.value", "value": "4"}, {"slot": "spec.displacement.value", "value": "1.6 L"},
        {"slot": "spec.weight.value", "value": "90 lb"}]})
    assert values["data"]["recorded"] == ["spec.cylinders.value", "spec.displacement.value"]
    assert [item["slot"] for item in values["data"]["refused"]] == ["spec.weight.value"]
    now = slots(client)
    # The approved names, then the CAD's weight row they left out.
    assert [row["key"] for row in now["sheet"]["rows"]] == ["cylinders", "displacement", "overall_dimensions",
                                                            "weight"]
    assert now["slots"]["spec.cylinders.value"]["source"] == "chat"
    assert now["slots"]["spec.cylinders.value"]["quote"].startswith("Yes, approve them.")
    assert now["slots"]["spec.weight.value"]["source"] == "cad"
    assert second.sheet_changes == ["approved the specification names", "recorded values you gave"]


def test_drafts_use_only_the_sheets_numbers_and_research_needs_a_source_read_this_turn(client):
    gateway = turn("Add a displacement row, write the tagline and the first feature, and look up the displacement.")
    assert call(gateway, "edit_specification_sheet", {"operation": "add_row", "label": "Displacement",
                                                      "unit": "L"})["ok"]
    drafted = call(gateway, "draft_specification_text", {"texts": [
        {"slot": "tagline", "text": "A compact four-cylinder engine, 92.3 lb as modelled."},
        {"slot": "feature.1.title", "text": "Rated at 110 hp"},
        {"slot": "spec.weight.value", "text": "about 92 lb"}]})
    assert drafted["data"]["drafted"] == ["tagline"]
    reasons = {item["slot"]: item["reason"] for item in drafted["data"]["refused"]}
    assert "110" in reasons["feature.1.title"] and "not a wording slot" in reasons["spec.weight.value"]
    read_id = "a" * 64
    gateway.research.results[read_id] = {
        "operation": "read", "requestedUrl": "https://example.com/x4", "retrievedAt": "2026-10-25T10:00:00Z",
        "summary": "The X4 engine displaces 1.6 litres and weighs 41.9 kg dry.",
        "sources": [{"url": "https://example.com/x4", "title": "X4 engine data"}]}
    gateway.research.results["c" * 64] = {"operation": "search", "summary": "1.6 L", "sources": []}
    recorded = call(gateway, "record_researched_values", {"values": [
        {"slot": "spec.displacement.value", "value": "1.6 L", "researchId": read_id, "note": "X4 petrol variant"},
        {"slot": "spec.weight.value", "value": "45 kg", "researchId": read_id},
        {"slot": "spec.displacement.value", "value": "1.6 L", "researchId": "c" * 64}]})
    assert recorded["data"]["recorded"] == ["spec.displacement.value"]
    assert {item["reason"][:24] for item in recorded["data"]["refused"]} == {
        "the source as read does ", "researchId is not a sour"}
    now = slots(client)
    value = now["slots"]["spec.displacement.value"]
    assert value["source"] == "research" and value["unreviewed"]
    assert value["citation"] == {"url": "https://example.com/x4", "title": "X4 engine data",
                                 "retrievedAt": "2026-10-25T10:00:00Z", "note": "X4 petrol variant"}
    assert value["value"] == "1.6 L"
    assert now["slots"]["tagline"]["source"] == "sage_draft" and now["slots"]["tagline"]["unreviewed"]
    assert call(gateway, "accept_specification_values", {"slots": ["tagline"]})["error"]["code"] == \
        "specification_approval_not_stated"
    accepted = call(turn("Accept the displacement and the tagline."), "accept_specification_values",
                    {"slots": ["spec.displacement.value", "tagline"]})
    assert sorted(accepted["data"]["accepted"]) == ["spec.displacement.value", "tagline"]
    assert not slots(client)["slots"]["tagline"]["unreviewed"]


def test_a_researched_list_keeps_one_item_per_line_and_the_pdf_draws_the_lines(client):
    # A robot's six axis ranges did not fit the old 40 characters and were squeezed into "+-180;+85/-65;...".
    document = client.get("/api/specification-sheet/100001/documentation-scene").json()["document"]
    assert _render(client, "100001", document).status_code == 200
    gateway = turn("Add an axis ranges row and look up the axis ranges.")
    added = call(gateway, "edit_specification_sheet", {"operation": "add_row", "label": "Axis motion ranges"})
    slot = f"spec.{added['data']['rowKey']}.value"
    read_id = "b" * 64
    gateway.research.results[read_id] = {
        "operation": "read", "requestedUrl": "https://example.com/robot", "retrievedAt": "2026-10-25T10:00:00Z",
        "summary": "Axis 1 +180 to -180, Axis 2 +85 to -65, Axis 3 +70 to -180, Axis 4 +300 to -300, "
                   "Axis 5 +120 to -120, Axis 6 +360 to -360 degrees.",
        "sources": [{"url": "https://example.com/robot", "title": "Robot data"}]}
    ranges = "\n".join(f"Axis {axis} {span}" for axis, span in enumerate(
        ("+180/-180", "+85/-65", "+70/-180", "+300/-300", "+120/-120", "+360/-360"), start=1))
    assert 40 < len(ranges) <= 120
    recorded = call(gateway, "record_researched_values", {"values": [
        {"slot": slot, "value": ranges, "researchId": read_id}]})
    assert recorded["data"]["recorded"] == [slot], recorded
    assert slots(client)["slots"][slot]["value"] == ranges
    too_long = call(gateway, "record_researched_values", {"values": [
        {"slot": slot, "value": "Axis 1 +180/-180, " * 7, "researchId": read_id}]})
    assert "error" in too_long and slots(client)["slots"][slot]["value"] == ranges
    exported = client.post("/api/specification-sheet/100001/pdf")
    assert exported.status_code == 200, exported.text
    lines = _pdf_text(client, exported.json()["pdf"]["url"]).splitlines()
    assert [line for line in lines if line[:5] == "Axis " and line[5:6].isdigit()] == ranges.split("\n")


def test_export_attaches_the_pdf_when_the_picture_is_current_and_queues_the_publish_otherwise(client):
    queued_turn = turn("Export the spec sheet")
    queued = call(queued_turn, "export_specification_sheet", {})
    assert queued["data"]["queued"] and queued_turn.queued[0]["name"] == "publish_specification_sheet"
    refused = call(turn("Export the fillable copy"), "export_specification_sheet", {"fillable": True})
    assert refused["error"]["code"] == "specification_capture_required"
    document = client.get("/api/specification-sheet/100001/documentation-scene").json()["document"]
    assert _render(client, "100001", document).status_code == 200
    exported_turn = turn("Export the fillable spec sheet")
    exported = call(exported_turn, "export_specification_sheet", {"fillable": True})
    assert exported["ok"], exported
    assert exported["data"]["openFields"] and not exported_turn.queued
    card = exported_turn.files[0]
    assert card["url"].endswith("/fillable-pdf") and card["detail"].endswith("open fields to fill")
    assert card["fileName"] == "100001 specification sheet (fillable).pdf"
    final = call(exported_turn, "export_specification_sheet", {})
    assert final["data"]["pdfUrl"].endswith("/pdf") and final["data"]["docxUrl"].endswith("/docx")
    assert [card["url"].rsplit("/", 1)[-1] for card in exported_turn.files] == ["fillable-pdf", "pdf"]
