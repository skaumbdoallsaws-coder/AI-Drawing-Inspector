"""P1b-2: real MMLE compilation, pure legacy reads and human-only confirmation."""
from __future__ import annotations

import ast
import asyncio
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import server
from ai_inspector.codex_runtime.documentation_tools import DocumentationGateway, tool_specs
from ai_inspector.documentation.commands import DocumentEditError
from ai_inspector.documentation.provenance import (
    EDITED_MARKER, EDITED_LEGEND, check_export, prepare_text_command, project_document, unconfirmed_targets,
)
from ai_inspector.documentation.targets import read_targets
from ai_inspector.operations_manual.artifacts import store_draft_render_artifact
from ai_inspector.operations_manual.evidence import OperationsManualEvidenceRepository
from ai_inspector.operations_manual.flow import FlowLayoutEngine
from ai_inspector.parts_manual.documentation import DocumentationSceneRepository
from ai_inspector.specification_sheet.slots import SlotStore
from tests.test_operations_manual_workspace import _png
from tools.documentation_baseline import docx_paragraphs

ROOT = Path(__file__).resolve().parents[1]
KIND = "operations_and_maintenance_manual"
BASE = "/api/operations-manual/MMLE-50D"
PAGE = "page-specifications-1"
CELL = "spec-table-1.r0.c1"


def disk(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def capacity(document):
    page = next(p for p in document["pages"] if p["pageId"] == PAGE)
    return next(b for b in page["layoutBlocks"] if b["blockId"] == "spec-table-1")


class Operations:
    def __init__(self, client, root):
        self.client, self.root = client, root

    def state(self):
        response = self.client.get(BASE + "/documentation-scene")
        assert response.status_code == 200, response.text
        return response.json()

    def edit(self, value="1,000 lb", *, page=PAGE, alias=CELL, operation="update_text", **extra):
        state = self.state()
        document = state["document"]
        body = {"baseRevision": state["revision"], "sourceRevision": document["sourceRevision"],
                "manualPlanRevision": document["manualPlanRevision"], "operation": operation,
                "pageId": page, "targetType": "page_element", "targetId": alias, **extra}
        if operation == "update_text":
            body["text"] = value
        response = self.client.post(BASE + "/documentation-scene/commands", json=body)
        assert response.status_code == 200, response.text
        return response.json()

    def read_confirmation(self):
        response = self.client.get(f"/api/documentation/{KIND}/MMLE-50D/confirmation-targets")
        assert response.status_code == 200, response.text
        data = response.json()
        return data, {"expectedRevision": data["revision"], "requestId": "confirm-test",
                      "targets": [{"targetId": target["targetId"], "expectedContentHash": target["contentHash"]}
                                  for target in data["targets"]]}

    def confirm(self, read=None, body=None):
        if read is None:
            read, body = self.read_confirmation()
        return self.client.post(f"/api/documentation/{read['documentId']}/confirm-values", json=body)

    def capture(self):
        document = self.state()["document"]
        png = _png()
        for page in document["pages"]:
            if page.get("renderRequest"):
                store_draft_render_artifact(self.root, "MMLE-50D", document, page["pageId"], png,
                    source_revision=document["sourceRevision"], manual_plan_revision=document["manualPlanRevision"])

    def export(self, mode="review"):
        response = self.client.post(BASE + "/pdf", params={"mode": mode})
        assert response.status_code == 200, response.text
        artifacts = response.json()
        import fitz

        with fitz.open(stream=self.client.get(artifacts["pdf"]["url"]).content, filetype="pdf") as pdf:
            pages = [page.get_text() for page in pdf]
        word = "\n".join(docx_paragraphs(self.client.get(artifacts["docx"]["url"]).content))
        return pages, word

    def history(self, direction):
        state = self.state()
        document = state["document"]
        response = self.client.post(BASE + "/documentation-scene/" + direction, json={
            "baseRevision": state["revision"], "sourceRevision": document["sourceRevision"],
            "manualPlanRevision": document["manualPlanRevision"]})
        assert response.status_code == 200, response.text
        return response.json()["document"]


@pytest.fixture
def operations(tmp_path, monkeypatch):
    monkeypatch.setattr(server, "OPERATIONS_MANUAL_ROOT", tmp_path / "om")
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "ss")
    monkeypatch.setattr(server, "_DOCUMENTATION_READ_BINDINGS", {})
    monkeypatch.setattr(server, "_FACILITY_PRINCIPAL_RESOLVER", lambda request: SimpleNamespace(principal_id="test-reviewer"))
    monkeypatch.setenv("INSPECTORPRO_CODEX_WEB_RESEARCH", "0")
    client = TestClient(server.app, base_url="http://127.0.0.1:8023")
    return Operations(client, server.OPERATIONS_MANUAL_ROOT)


def test_cited_cell_edit_invalidates_support(operations):
    before = capacity(operations.state()["document"])["rows"][0]
    changed = operations.edit()
    row = capacity(changed["document"])["rows"][0]
    meta = row["provenance"]
    assert meta["origin"] == "manual" and meta["evidenceStatus"] == "edited_unverified"
    assert meta["marker"] == EDITED_MARKER
    assert meta["originalEvidence"]["claimIds"] == ["CLM-SPEC-001"]
    assert meta["originalEvidence"]["sourceIds"] == before["sourceIds"]
    assert meta["generatedValue"][CELL] == "1,100 lb" and meta["generatedHash"]
    assert meta["changeId"] and meta["actor"] == "user"
    assert row["claimIds"] == [] and row["sourceIds"] == []
    assert meta["activeClaimIds"] == [] and meta["activeSourceIds"] == []
    assert changed["scene"]["fieldMeta"][meta["targetId"]]["evidenceStatus"] == "edited_unverified"
    assert all(not item["claimIds"] for item in changed["document"]["sourceSupport"] if item["targetId"] == meta["targetId"])


def test_plan_row_bindings_survive_compilation_and_pagination(operations):
    document = operations.state()["document"]  # The real ignored MMLE profile and registered claims.
    assert document["schemaVersion"] == 2
    block = capacity(document)
    assert block["evidenceBindingVersion"] == 1
    assert all(len(row["cells"]) == 2 for row in block["rows"])
    snapshot = OperationsManualEvidenceRepository(ROOT / "docs/operations-manual").snapshot()
    for row in block["rows"]:
        assert len(row["claimIds"]) == 1
        assert row["sourceIds"] == snapshot["claims"][row["claimIds"][0]]["sourceIds"]
    # A long explicitly bound row is copied through every split fragment.
    sections = [{"sectionId": "split", "title": "Split", "blocks": [{
        "blockId": "long", "blockType": "table", "readingOrder": 1,
        "evidenceBindingVersion": 1, "evidenceClaimIds": ["CLM-SPEC-001"],
        "payload": {"columns": ["Name", "Value"], "rows": [{
            "cells": ["Capacity", "Long value " * 1500], "claimIds": ["CLM-SPEC-001"],
            "sourceIds": ["SRC-OEM-MMLE-WEB-2026"]}]}}]}]
    pages = FlowLayoutEngine(start_page_number=1).layout(sections)
    fragments = [b for page in pages for b in page["layoutBlocks"] if b["blockType"] == "table"]
    assert len(fragments) > 1
    assert any(row.get("rowContinuation") for b in fragments for row in b["rows"])
    for fragment in fragments:
        assert fragment["evidenceBindingVersion"] == 1
        assert all(row["claimIds"] == ["CLM-SPEC-001"] and row["sourceIds"] == ["SRC-OEM-MMLE-WEB-2026"]
                   for row in fragment["rows"])


def test_capacity_edit_preserves_other_rows_claims(operations):
    original = capacity(operations.state()["document"])
    changed = capacity(operations.edit()["document"])
    assert changed["rows"][0]["claimIds"] == []
    assert [(row["claimIds"], row["sourceIds"]) for row in changed["rows"][1:]] == [
        (row["claimIds"], row["sourceIds"]) for row in original["rows"][1:]]
    assert changed["evidenceClaimIds"] == original["evidenceClaimIds"]  # Compatibility receipt.
    assert "CLM-SPEC-001" not in changed["activeEvidenceClaimIds"]
    assert all(row["provenance"]["evidenceStatus"] == "source_backed" for row in changed["rows"][1:])


def old_document():
    return {"schemaVersion": 1, "documentType": KIND, "product": {"assemblyNumber": "legacy"},
        "sourceRevision": "source", "manualPlanRevision": "plan", "evidenceCitations": [{
            "sourceId": "source-oem", "authority": "OEM_CURRENT", "claimIds": ["capacity", "travel"]}],
        "pages": [{"pageId": "page-old", "layoutBlocks": [{"blockId": "old", "blockType": "table",
            "evidenceClaimIds": ["capacity", "travel"], "rows": [{"cells": ["Capacity", "1,100 lb"]},
                                                                   {"cells": ["Travel", "20 in"]}]}]}]}


def test_old_compiled_block_uses_conservative_fallback(tmp_path):
    old = old_document()
    old["pages"][0]["documentationComposition"] = {"pageElementOverrides": {"old.r0.c1": {"text": "1,000 lb"}}}
    path = tmp_path / "old.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    raw = path.read_bytes()
    projected = project_document(json.loads(raw))
    assert path.read_bytes() == raw and old["schemaVersion"] == 1
    block = projected["pages"][0]["layoutBlocks"][0]
    assert projected["schemaVersion"] == 2 and "evidenceBindingVersion" not in block
    assert block["provenance"]["evidenceStatus"] == "edited_unverified"
    assert block["activeEvidenceClaimIds"] == []
    assert block["originalEvidence"]["claimIds"] == ["capacity", "travel"]
    assert len(projected["provenanceTargets"]) == 1
    assert set(projected["provenanceTargets"][0]["values"]) == {"old.r0.c0", "old.r0.c1", "old.r1.c0", "old.r1.c1"}
    assert unconfirmed_targets(projected)[0]["alias"] == "old"
    with pytest.raises(DocumentEditError) as rejected:
        check_export(old, "customer")
    assert rejected.value.code == "unconfirmed_cited_values"
    assert rejected.value.details["targets"] == unconfirmed_targets(projected)


def test_legacy_override_marked_edited(tmp_path):
    repo = DocumentationSceneRepository(tmp_path, KIND)
    initial = repo.read("legacy", "source", "plan")
    saved = repo.apply_command("legacy", "source", "plan", base_revision=initial["revision"],
        command={"operation": "update_text", "pageId": "page-old", "targetType": "page_element",
                 "targetId": "old.r0.c1", "text": "1,000 lb"},
        page_targets={"page-old": {"page_element": ["old.r0.c1"]}})
    path = tmp_path / "legacy/documentation-scene.json"
    legacy = json.loads(path.read_text(encoding="ascii"))
    legacy.pop("fieldMeta")  # P1a scene-3 shape, before provenance keys existed.
    path.write_text(json.dumps(legacy), encoding="ascii")
    before = disk(tmp_path)
    loaded = repo.read("legacy", "source", "plan")
    old = old_document()
    old["pages"][0]["documentationComposition"] = loaded["scene"]["pages"]["page-old"]
    projected = project_document(old, loaded["scene"])
    assert projected["provenanceTargets"][0]["provenance"]["evidenceStatus"] == "edited_unverified"
    assert disk(tmp_path) == before
    command = prepare_text_command(projected, {"operation": "update_text", "pageId": "page-old",
        "targetType": "page_element", "targetId": "old.r0.c1", "text": "900 lb"})
    adopted = repo.apply_command("legacy", "source", "plan", base_revision=loaded["revision"], command=command,
                                page_targets={"page-old": {"page_element": ["old.r0.c1"]}})
    assert adopted["scene"]["schemaVersion"] == 3 and adopted["scene"]["fieldMeta"]
    assert saved["scene"]["schemaVersion"] == 3


def test_paragraph_and_list_item_binding_scope():
    old = old_document()
    old["pages"][0]["layoutBlocks"] = [
        {"blockId": "para", "blockType": "paragraph", "text": "Capacity is 1,100 lb.", "evidenceClaimIds": ["capacity"]},
        {"blockId": "list", "blockType": "list", "evidenceBindingVersion": 1,
         "evidenceClaimIds": ["capacity", "travel"], "items": [
             {"text": "Capacity is 1,100 lb.", "claimIds": ["capacity"], "sourceIds": ["source-oem"]},
             {"text": "Travel is 20 in.", "claimIds": ["travel"], "sourceIds": ["source-oem"]}]}]
    old["pages"][0]["documentationComposition"] = {"pageElementOverrides": {
        "para": {"text": "New prose."}, "list.i0": {"text": "New item."}}}
    document = project_document(old)
    para, listing = document["pages"][0]["layoutBlocks"]
    assert para["provenance"]["evidenceStatus"] == "edited_unverified"
    assert listing["items"][0]["claimIds"] == [] and listing["items"][1]["claimIds"] == ["travel"]
    assert {item["alias"] for item in unconfirmed_targets(document)} == {"para", "list.i0"}
    # A partially bound list retains the known item scope. An unknown item marks all values.
    old["pages"][0]["layoutBlocks"][1]["items"][1].pop("claimIds")
    assert {item["alias"] for item in unconfirmed_targets(project_document(old))} == {"para", "list.i0"}
    old["pages"][0]["documentationComposition"]["pageElementOverrides"]["list.i1"] = {"text": "Unknown binding edit."}
    fallback = project_document(old)
    assert {item["alias"] for item in unconfirmed_targets(fallback)} == {"para", "list"}
    assert all(not item.get("claimIds") for item in fallback["pages"][0]["layoutBlocks"][1]["items"])


def test_format_only_preserves_citation(operations):
    original = capacity(operations.state()["document"])["rows"][0]["provenance"]
    formatted = operations.edit(operation="update_style", style={"fontWeight": 700})["document"]
    assert capacity(formatted)["rows"][0]["provenance"] == original
    same = operations.edit("1,100 lb")["document"]
    assert capacity(same)["rows"][0]["provenance"]["evidenceStatus"] == "source_backed"
    operations.edit()
    typed_back = operations.edit("1,100 lb")["document"]
    assert capacity(typed_back)["rows"][0]["provenance"]["evidenceStatus"] == "edited_unverified"


def sage(operations):
    return DocumentationGateway(server._DocumentationAgentHost(),
        SimpleNamespace(tenant_id="test", principal_id="sage-test", roles=(), allowed_site_ids=()),
        {"assemblyNumber": "MMLE-50D", "documentType": KIND}, turn_id="provenance-test")


def call(gateway, name, arguments):
    result = asyncio.run(gateway.call(name, arguments))
    assert result["ok"], result
    return result["data"]


def test_pdf_docx_and_sage_show_edited(operations):
    operations.capture()
    operations.edit()
    pages, word = operations.export()
    assert any("Rated capacity" in page and EDITED_MARKER in page and EDITED_LEGEND in page for page in pages)
    assert EDITED_MARKER in word and EDITED_LEGEND in word and "1,000 lb" in word
    read = call(sage(operations), "read_document_pages", {"documentType": KIND,
                "targets": [{"pageId": PAGE, "targetId": CELL}]})
    meta = read["targets"][0]["provenance"]
    assert meta["marker"] == EDITED_MARKER and meta["activeClaimIds"] == []
    assert read["confirmationTargets"][0]["alias"] == "spec-table-1.r0"
    assert meta["evidenceStatus"] == "edited_unverified"


def test_slot_overrides_keep_existing_findings(operations):
    client = operations.client
    baseline = client.get("/api/specification-sheet/MMLE-50D/documentation-scene").json()["document"]
    assert baseline["schemaVersion"] == 2
    changed = client.post("/api/specification-sheet/MMLE-50D/values", json={"values": [
        {"slot": "spec.rated_capacity.value", "value": "1,000 lb"}]}).json()["document"]
    slot = changed["slots"]["spec.rated_capacity.value"]
    assert slot["source"] == "workspace" and slot["overrides"]["source"] == "evidence"
    assert slot["claimIds"] == ["CLM-SPEC-001"]  # Existing engineering gate input stays intact.
    assert slot["activeClaimIds"] == [] and slot["provenance"]["evidenceStatus"] == "edited_unverified"
    assert "overrides_evidence" in {finding["topic"] for finding in changed["releaseGate"]["findings"]}
    stored = SlotStore(server.SPECIFICATION_SHEET_ROOT, "MMLE-50D").read()
    assert stored["schemaVersion"] == 2 and stored["fieldMeta"]["slot:spec.rated_capacity.value"]
    refused = client.post("/api/specification-sheet/MMLE-50D/pdf?mode=customer")
    assert refused.status_code == 422 and refused.json()["error"] == "unconfirmed_cited_values"
    assert refused.json()["details"]["targets"] == unconfirmed_targets(changed)
    client.post("/api/specification-sheet/100001/generate?rebaseline=true")
    cad = client.post("/api/specification-sheet/100001/values", json={"values": [
        {"slot": "spec.weight.value", "value": "95 lb"}]}).json()["document"]
    assert "overrides_cad" in {finding["topic"] for finding in cad["releaseGate"]["findings"]}
    assert cad["slots"]["spec.weight.value"]["overrides"]["source"] == "cad"


def test_unconfirmed_customer_export_blocked(operations):
    changed = operations.edit()["document"]
    expected = unconfirmed_targets(changed)
    assert len(expected) == 1 and expected[0]["alias"] == "spec-table-1.r0"
    for mode in ("customer", "controlled"):
        response = operations.client.post(BASE + "/pdf", params={"mode": mode})
        assert response.status_code == 422
        assert response.json()["error"] == "unconfirmed_cited_values"
        assert response.json()["details"]["targets"] == expected
    with pytest.raises(DocumentEditError, match="Confirm or undo"):
        check_export(changed, "customer")


def test_user_confirmation_removes_active_citation(operations):
    operations.edit()
    read, body = operations.read_confirmation()
    assert set(read["targets"][0]["values"]) == {"spec-table-1.r0.c0", CELL}
    response = operations.confirm(read, body)
    assert response.status_code == 200, response.text
    receipt = response.json()["receipt"]
    assert receipt["undoable"] and receipt["changedIds"] == [read["targets"][0]["targetId"]]
    meta = capacity(operations.state()["document"])["rows"][0]["provenance"]
    assert meta["evidenceStatus"] == "entered_by_user" and meta["activeClaimIds"] == []
    assert meta["confirmation"]["by"] == "test-reviewer"
    assert meta["confirmation"]["at"] and meta["confirmation"]["valueHash"]
    assert meta["confirmation"]["changeId"] == receipt["changeId"]
    assert meta["originalEvidence"]["claimIds"] == ["CLM-SPEC-001"]
    assert project_document(operations.state()["document"])["fieldMeta"][meta["targetId"]] == meta
    saved = disk(operations.root)
    assert operations.confirm(read, body).json()["receipt"] == receipt
    assert disk(operations.root) == saved  # One receipt, identical retry, no write.
    undone = operations.history("undo")
    assert capacity(undone)["rows"][0]["provenance"]["evidenceStatus"] == "edited_unverified"
    restored = operations.history("undo")
    assert capacity(restored)["rows"][0]["provenance"]["evidenceStatus"] == "source_backed"


def test_sage_cannot_confirm_value(operations):
    operations.edit()
    gateway = sage(operations)
    read = call(gateway, "read_document_pages", {"documentType": KIND,
                "targets": [{"pageId": PAGE, "targetId": CELL}]})
    args = {"documentId": read["documentId"], "targets": [{"targetId": row["targetId"],
            "expectedContentHash": row["contentHash"]} for row in read["confirmationTargets"]]}
    before = disk(operations.root)
    proposal = call(gateway, "propose_document_value_confirmation", args)
    assert proposal == {"proposalId": proposal["proposalId"], **args, "status": "awaiting_user"}
    assert disk(operations.root) == before
    denied = asyncio.run(gateway.call("confirm_document_values", args))
    assert not denied["ok"] and denied["error"]["code"] == "codex_tool_denied"
    assert next(spec for spec in tool_specs() if spec["name"] == "propose_document_value_confirmation")["read_only"]
    # Both registered server tool modules and the browser executor must stay outside
    # the human mutation path. This fails even for an indirect call to the handler.
    forbidden = ("/confirm-values", "documentation_confirm_values", "confirmation_command(", "allow_confirmation=True", ".confirm_values(")
    paths = list((ROOT / "ai_inspector/codex_runtime").glob("*tools.py")) + [ROOT / "ai_inspector/documentation/agent_tools.py"]
    for path in paths:
        source = path.read_text(encoding="utf-8")
        assert not any(token in source for token in forbidden), path
    source = (ROOT / "server.py").read_text(encoding="utf-8-sig")
    tree = ast.parse(source)
    host = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "_DocumentationAgentHost")
    assert not any(token in ast.get_source_segment(source, host) for token in forbidden)
    browser = (ROOT / "static/index.html").read_text(encoding="utf-8")
    assert "executeAgentTool" in browser and "executeToolCall(toolCall, originAgent)" in browser
    assert not any(token in browser for token in forbidden)
    registry = browser.split("const TOOL_REGISTRY = {", 1)[1].split("const TOOL_TIMEOUT_MS =", 1)[0]
    assert "confirmationControl" not in registry and "confirm_values" not in registry
    assert "confirmValue" not in registry
    ui = (ROOT / "static/documentation_commands.js").read_text(encoding="utf-8")
    assert ui.count("/confirm-values") == 1
    trusted_handler = ui.split("confirm.addEventListener('click'", 1)[1].split("const cancel =", 1)[0]
    assert "/confirm-values" in trusted_handler
    assert trusted_handler.index("!click.isTrusted") < trusted_handler.index("/confirm-values")
    assert "if (!event.isTrusted || !isCurrent()) return;" in ui
    assert "if (!click.isTrusted || !isCurrent()) return;" in ui
    assert "Confirm as entered by me" in ui and "Original source:" in ui
    # There is no metadata/actor escape hatch through a normal command.
    state = operations.state()
    forged = operations.client.post(BASE + "/documentation-scene/commands", json={
        "baseRevision": state["revision"], "sourceRevision": state["document"]["sourceRevision"],
        "manualPlanRevision": state["document"]["manualPlanRevision"], "operation": "confirm_value",
        "pageId": PAGE, "targetType": "page_element", "targetId": CELL})
    assert forged.status_code == 422
    assert disk(operations.root) == before


def test_confirmation_stale_click_rejected(operations):
    operations.edit()
    read, body = operations.read_confirmation()
    operations.edit("950 lb")
    before = disk(operations.root)
    response = operations.confirm(read, body)
    assert response.status_code == 422 and response.json()["error"] == "stale_revision"
    current, payload = operations.read_confirmation()
    payload["targets"][0]["expectedContentHash"] = "0" * 64
    response = operations.confirm(current, payload)
    assert response.status_code == 422 and response.json()["error"] == "content_hash_mismatch"
    url = f"/api/documentation/{current['documentId']}/confirm-values"
    for headers in ({"Origin": "https://attacker.example"},
                    {"Host": "attacker.example", "Origin": "http://attacker.example"}):
        refused = operations.client.post(url, json=payload, headers=headers)
        assert refused.status_code == 403 and refused.json()["error"]["code"] == "documentation_origin_forbidden"
        preflight = operations.client.options(url, headers={**headers, "Access-Control-Request-Method": "POST"})
        assert preflight.status_code == 403
        assert "access-control-allow-origin" not in preflight.headers
    assert disk(operations.root) == before


def test_confirmed_customer_copy_has_no_warning_or_oem_citation(operations):
    operations.capture()
    operations.edit()
    assert operations.confirm().status_code == 200
    document = operations.state()["document"]
    row = capacity(document)["rows"][0]
    assert not row["claimIds"] and not row["sourceIds"]
    assert row["provenance"]["marker"] == "" and row["provenance"]["evidenceStatus"] == "entered_by_user"
    assert any(row["claimIds"] for row in capacity(document)["rows"][1:])
    pages, word = operations.export("customer")
    assert any("Rated capacity" in page and "1,000 lb" in page for page in pages)
    assert "1,000 lb" in word
    assert EDITED_MARKER not in "\n".join(pages) and EDITED_MARKER not in word
    assert EDITED_LEGEND not in word and "OEM current" not in word
    # Independent page-6 source prose remains unchanged; no cross-document reconciliation.
    assert any("1,100 lb" in page for page in pages)


def test_edit_clears_confirmation(operations):
    operations.edit()
    assert operations.confirm().status_code == 200
    confirmed = capacity(operations.state()["document"])["rows"][0]["provenance"]
    same = operations.edit()["document"]
    assert capacity(same)["rows"][0]["provenance"]["confirmation"] == confirmed["confirmation"]
    changed = operations.edit("900 lb")["document"]
    meta = capacity(changed)["rows"][0]["provenance"]
    assert "confirmation" not in meta and meta["evidenceStatus"] == "edited_unverified"
    restored = operations.history("undo")
    assert capacity(restored)["rows"][0]["provenance"]["confirmation"] == confirmed["confirmation"]


def test_confirmation_is_atomic_and_rejects_cell_instead_of_row(operations):
    operations.edit()
    read, body = operations.read_confirmation()
    body["targets"].append({"targetId": "spec-table-1.r0.c1", "expectedContentHash": "0" * 64})
    before = disk(operations.root)
    response = operations.confirm(read, body)
    assert response.status_code == 422 and response.json()["error"] == "target_not_found"
    assert disk(operations.root) == before
    assert capacity(operations.state()["document"])["rows"][0]["provenance"]["evidenceStatus"] == "edited_unverified"


def test_legacy_slot_metadata_is_read_only_and_adopted_on_first_edit(operations):
    store = SlotStore(server.SPECIFICATION_SHEET_ROOT, "MMLE-50D")
    store.set_values([{"slot": "spec.rated_capacity.value", "value": "1,000 lb"}], "workspace")
    old = json.loads(store.path.read_text(encoding="utf-8"))
    old.pop("fieldMeta")
    store.path.write_text(json.dumps(old), encoding="utf-8")
    before = disk(server.SPECIFICATION_SHEET_ROOT)
    response = operations.client.get("/api/specification-sheet/MMLE-50D/documentation-scene")
    assert response.status_code == 200, response.text
    slot = response.json()["document"]["slots"]["spec.rated_capacity.value"]
    assert slot["provenance"]["evidenceStatus"] == "edited_unverified"
    assert disk(server.SPECIFICATION_SHEET_ROOT) == before
    changed = operations.client.post("/api/specification-sheet/MMLE-50D/values", json={"values": [
        {"slot": "spec.rated_capacity.value", "value": "900 lb"}]})
    assert changed.status_code == 200, changed.text
    adopted = store.read()
    assert adopted["schemaVersion"] == 2 and adopted["fieldMeta"]["slot:spec.rated_capacity.value"]


def test_old_parts_document_projects_schema_five_without_writing(tmp_path):
    old = {"schemaVersion": 4, "documentType": "illustrated_parts_manual", "sourceRevision": "source",
           "manualPlanRevision": "plan", "product": {"assemblyNumber": "legacy", "name": "Machine"},
           "pages": [{"pageId": "page-cover", "pageType": "cover", "bom": []}]}
    path = tmp_path / "parts.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    before = path.read_bytes()
    current = project_document(json.loads(before))
    assert current["schemaVersion"] == 5 and current["fieldMeta"]
    assert all(meta["origin"] == "generated" and meta["evidenceStatus"] == "unbound"
               for meta in current["fieldMeta"].values())
    assert path.read_bytes() == before
