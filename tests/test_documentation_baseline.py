"""P0 contracts. Missing local inputs skip only the optional MMLE integration."""

import io
import json
from types import SimpleNamespace
from unittest.mock import Mock
import zipfile

import pytest

from tools import documentation_baseline as baseline


def test_semantic_fingerprint_preserves_content_identity_evidence_and_order():
    original = {"updatedAt": "yesterday", "text": " A\nB ", "sourceRevision": "rev-a",
                "claimIds": ["a", "b"], "rowId": "row-a", "frame": {"x": 0.1}}
    clock_only = {**original, "updatedAt": "today"}
    assert baseline.fingerprint(baseline.semantic(original)) == baseline.fingerprint(baseline.semantic(clock_only))
    for key, value in (("text", "A B"), ("sourceRevision", "rev-b"), ("claimIds", ["b", "a"]),
                       ("rowId", "row-b"), ("frame", {"x": 0.2})):
        assert baseline.fingerprint(baseline.semantic(original)) != baseline.fingerprint(
            baseline.semantic({**original, key: value}))


def test_docx_text_fingerprint_includes_nested_cells_in_document_order():
    def package(text):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", text)
        return buffer.getvalue()

    xml = ('<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
           '<w:body><w:p><w:r><w:t>A</w:t></w:r><w:r><w:t>B</w:t></w:r></w:p>'
           '<w:tbl><w:tr><w:tc><w:p><w:r><w:t>C</w:t><w:tab/><w:t>D</w:t></w:r></w:p>'
           '</w:tc></w:tr></w:tbl></w:body></w:document>')
    result = baseline.docx_fingerprint(package(xml))
    assert result == {"textSha256": baseline.fingerprint("AB\nC\tD"), "characters": 6, "paragraphs": 2}
    assert result != baseline.docx_fingerprint(package(xml.replace(">C<", ">X<")))


def test_pending_expectations_cannot_pass():
    with pytest.raises(AssertionError, match="pending"):
        baseline.compare({}, {"status": "awaiting_supervisor_capture"})


def test_comparison_does_not_accept_a_changed_export():
    with pytest.raises(AssertionError, match="parts"):
        baseline.compare({"status": "captured", "parts": {"pdf": "changed"}},
                         {"status": "captured", "parts": {"pdf": "old"}})


def test_private_and_outside_paths_are_rejected():
    for name in (".env", ".env.local", "ui-data/private.json", "../outside.json"):
        with pytest.raises(ValueError):
            baseline.safe_source(name)


def test_tracked_fixture_inventory_remains_explicit():
    expected = json.loads((baseline.EXPECTED.parent / "inventory.json").read_text(encoding="ascii"))
    assert baseline.inventory() == expected


def test_documentation_baseline_matches_recorded_expectations():
    """Production repository APIs, export extraction, undo and reopen on fresh stores."""
    expected = json.loads(baseline.EXPECTED.read_text(encoding="ascii"))
    baseline.compare(baseline.collect(), expected)


def test_local_inputs_absent_reports_skip_without_importing_server(tmp_path, monkeypatch, capsys):
    inventory = baseline.local_inventory(tmp_path)
    assert inventory["available"] is False and inventory["missingInputs"]
    monkeypatch.setattr(baseline, "local_inventory", lambda: inventory)
    result = baseline.collect_local()
    assert result["status"] == "skipped" and result["reason"] == "local inputs absent"
    with pytest.raises(AssertionError, match="not a passing baseline"):
        baseline.compare(result, {"status": "captured"})
    assert baseline.main(["--local", "--check"]) == 3
    output = capsys.readouterr().out
    assert "skipped: local inputs absent" in output
    assert "baseline matches" not in output


def test_local_documentation_baseline_matches_recorded_expectations():
    result = baseline.collect_local()
    if result["status"] == "skipped":
        pytest.skip("skipped: local inputs absent")
    expected = json.loads(baseline.EXPECTED_LOCAL.read_text(encoding="ascii"))
    baseline.compare(result, expected)


def _compiled_citation_fixture():
    return {
        "pages": [
            {"pageId": "page-specifications-1", "layoutBlocks": [
                {"blockId": "spec-table-1", "blockType": "table", "evidenceClaimIds": ["CLM-SPEC-001", "CLM-SPEC-002"],
                 "rows": [{"cells": ["Rated capacity", "1,000 lb"]}]}]},
            {"pageId": "page-sources-1", "layoutBlocks": [
                {"blockId": "sources-table-1", "sourceBlockId": "sources-table", "rows": [
                    {"cells": ["Manufacturer specifications", "Current manufacturer source; cited by 2 claims"]}]}]},
        ],
        "evidenceCitations": [{"sourceId": "SRC-001", "title": "Manufacturer specifications",
                               "authority": "OEM_CURRENT", "url": None, "claimIds": ["CLM-SPEC-001", "CLM-SPEC-002"]}],
    }


def test_local_citation_probe_uses_compiled_block_claims_and_export_source_register():
    document = _compiled_citation_fixture()
    page, block = baseline.local_citation_target(document)
    assert page["pageId"] == "page-specifications-1" and block["blockId"] == "spec-table-1"
    state = baseline.local_citation_state(document, block)
    assert state["rowKeys"] == ["cells"] and state["cells"] == ["Rated capacity", "1,000 lb"]
    assert state["evidenceClaimIds"] == ["CLM-SPEC-001", "CLM-SPEC-002"]
    assert state["claimCitations"] == [{"sourceId": "SRC-001", "title": "Manufacturer specifications",
                                        "authority": "OEM_CURRENT", "url": None}]
    texts = {"pdf": ["Rated capacity\n1,000 lb", "Manufacturer\nspecifications\nCurrent manufacturer source; cited by 2 claims"],
             "docx": "Rated capacity\n1,000 lb\nManufacturer specifications\nCurrent manufacturer source; cited by 2 claims"}
    result = baseline.local_citation_export(document, block, texts)
    assert result["pdf"] == {"valuePageNumbers": [1], "rowPageNumbers": [1]}
    assert result["docx"] == {"valuePresent": True, "rowPresent": True}
    assert result["sourceRegister"] == [{
        "sourceId": "SRC-001", "authority": "OEM_CURRENT", "pageId": "page-sources-1", "blockId": "sources-table-1",
        "cells": ["Manufacturer specifications", "Current manufacturer source; cited by 2 claims"],
        "pdfPageNumbers": [2], "docxRowPresent": True}]
    # Losing authority text must be visible even if the edited value still exports.
    texts["pdf"][1] = "Manufacturer specifications"
    texts["docx"] = "Rated capacity\n1,000 lb\nManufacturer specifications"
    missing_authority = baseline.local_citation_export(document, block, texts)["sourceRegister"][0]
    assert missing_authority["pdfPageNumbers"] == [] and missing_authority["docxRowPresent"] is False


def test_local_citation_probe_rejects_value_elsewhere_in_exports():
    document = _compiled_citation_fixture()
    _, block = baseline.local_citation_target(document)
    for kind in ("pdf", "docx"):
        texts = {"pdf": ["Rated capacity\n1,000 lb"], "docx": "Rated capacity\n1,000 lb"}
        unrelated = "Rated capacity\n1,100 lb\nUnrelated limit\n1,000 lb"
        texts[kind] = [unrelated] if kind == "pdf" else unrelated
        with pytest.raises(AssertionError, match=kind.upper()):
            baseline.local_citation_export(document, block, texts)


def _work_instruction_capture_fixture():
    return {"documentRevision": "edited-revision", "sourceRevision": "source-revision", "manualPlanRevision": "plan-revision",
            "pages": [{"pageId": "page-work-instructions-cover", "renderRequest": {"image": {"status": "pending"}}},
                      {"pageId": "page-operation-1", "renderRequest": {"image": {"status": "ready"}}},
                      {"pageId": "page-without-figure"}]}


def test_work_instruction_text_capture_probe_recaptures_only_pending_pages_at_current_revision(tmp_path):
    document = _work_instruction_capture_fixture()
    original = baseline.fingerprint(document)
    refusal = {"error": "work_instruction_capture_required", "status": "CAPTURE_REQUIRED",
               "documentRevision": document["documentRevision"], "requiredCaptureCount": 1,
               "pendingPages": [{"pageId": "page-work-instructions-cover", "pageNumber": 1, "title": "Cover"}]}
    client = SimpleNamespace(post=Mock(return_value=SimpleNamespace(status_code=422, text="capture required", json=lambda: refusal)))
    capture, writer = Mock(return_value=b"capture bytes"), Mock()
    facts, receipt = baseline.work_instruction_text_capture_probe(client, tmp_path, document, capture, writer)
    assert facts == {"textEditInvalidatesPageCapture": True,
                     "pagesNeedingCaptureAfterTextEdit": ["page-work-instructions-cover"],
                     "textEditExportHttpStatus": 422, "recapturedPageIds": ["page-work-instructions-cover"]}
    assert receipt is None  # Caller must export again after recapture, not fingerprint the refusal.
    client.post.assert_called_once_with("/api/work-instructions/MMLE-50D/pdf")
    capture.assert_called_once_with(1920, 1080)
    writer.assert_called_once_with(tmp_path, "MMLE-50D", document, "page-work-instructions-cover", b"capture bytes",
                                   source_revision="source-revision", manual_plan_revision="plan-revision",
                                   api_route="work-instructions")
    assert baseline.fingerprint(document) == original


def test_work_instruction_text_capture_probe_ready_export_needs_no_recapture(tmp_path):
    receipt = {"pdf": {"url": "/pdf"}, "docx": {"url": "/docx"}}
    client = SimpleNamespace(post=Mock(return_value=SimpleNamespace(status_code=200, text="ready", json=lambda: receipt)))
    capture, writer = Mock(), Mock()
    facts, exported = baseline.work_instruction_text_capture_probe(client, tmp_path, _work_instruction_capture_fixture(), capture, writer)
    assert facts == {"textEditInvalidatesPageCapture": False, "pagesNeedingCaptureAfterTextEdit": [],
                     "textEditExportHttpStatus": 200, "recapturedPageIds": []}
    assert exported is receipt  # Reuse this export's downloads without a duplicate POST.
    capture.assert_not_called()
    writer.assert_not_called()


def test_work_instruction_text_capture_probe_does_not_repair_other_failures(tmp_path):
    document = _work_instruction_capture_fixture()
    refusal = {"error": "work_instruction_capture_required", "status": "CAPTURE_REQUIRED",
               "documentRevision": document["documentRevision"], "requiredCaptureCount": 1,
               "pendingPages": [{"pageId": "page-work-instructions-cover"}]}
    for status, body in ((500, {}), (422, {**refusal, "error": "release_blocked"}),
                         (422, {**refusal, "documentRevision": "old-revision"}),
                         (422, {**refusal, "pendingPages": [{"pageId": "page-without-figure"}]})):
        client = SimpleNamespace(post=Mock(return_value=SimpleNamespace(status_code=status, text="refused", json=lambda: body)))
        capture, writer = Mock(), Mock()
        with pytest.raises(AssertionError):
            baseline.work_instruction_text_capture_probe(client, tmp_path, document, capture, writer)
        capture.assert_not_called()
        writer.assert_not_called()


def test_specification_capture_exports_under_figure_revision(tmp_path):
    from PIL import Image
    from ai_inspector.parts_manual.catalog import build_occurrence_catalog
    from ai_inspector.specification_sheet.document import build_specification_sheet_document
    from ai_inspector.specification_sheet.exports import build_specification_pdf_bytes, build_specification_docx_bytes
    from ai_inspector.specification_sheet.slots import SlotStore
    from ai_inspector.operations_manual.artifacts import draft_render_path

    fixture = baseline.fixture_functions("tests/test_parts_manual.py", {"_assembly_profile"}, {})
    profile = fixture["_assembly_profile"]()
    assembly = "manual-fixture"
    catalog = build_occurrence_catalog(assembly, profile)
    payload = io.BytesIO()
    Image.new("RGB", (2200, 2200), "white").save(payload, format="PNG")

    def build():
        return build_specification_sheet_document(profile, catalog, evidence_root=tmp_path / "ev",
                                                 profile_root=tmp_path / "pr", slot_root=tmp_path)

    before = build()
    SlotStore(tmp_path, assembly).set_values([{"slot": "tagline", "value": "Edited product text."}], "workspace")
    after = build()
    assert before["figureRevision"] == after["figureRevision"]
    assert before["documentRevision"] != after["documentRevision"]
    for document in (before, after):
        attached = baseline.specification_capture(tmp_path, assembly, document, payload.getvalue())
        page = attached["pages"][0]
        image = page["renderRequest"]["image"]
        assert image["status"] == "ready"
        assert image["figureRevision"] == document["figureRevision"]
        assert image["documentRevision"] == document["documentRevision"]
        assert draft_render_path(tmp_path, assembly, document["figureRevision"], page["pageId"]).is_file()
        assert build_specification_pdf_bytes(attached, render_root=tmp_path, assembly_number=assembly).startswith(b"%PDF")
        docx = build_specification_docx_bytes(attached, render_root=tmp_path, assembly_number=assembly)
        assert baseline.docx_fingerprint(docx)["characters"] > 0
