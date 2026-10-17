"""Synthetic reader contracts plus optional checks of the private document set."""
from copy import deepcopy
import hashlib
import json

import fitz
import pytest

from ai_inspector.research.equipment_documents import EquipmentDocumentLibrary, INDEX_PATH
from ai_inspector.research.web import ResearchError


def sha(data):
    return hashlib.sha256(data).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value), encoding="utf-8")


@pytest.fixture
def library(tmp_path):
    with fitz.open() as pdf:
        for number in range(45):
            page = pdf.new_page()
            if number != 44:
                page.insert_text((40, 40), f"Model Alpha page {number + 1}. Nominal payload 10 kg; option X only.")
            if number == 40:
                page.insert_text((40, 60), "Distinctive tooling condition.")
        pdf[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(40, 28, 550, 44), "page": 40})
        pdf[0].insert_link({"kind": fitz.LINK_GOTO, "from": fitz.Rect(40, 50, 550, 64), "page": 41})
        pdf[0].insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(40, 70, 550, 84), "uri": "https://external.example/not-fetched"})
        pdf.save(tmp_path / "manual.pdf")
    doc = {"file": "manual.pdf", "sha256": sha((tmp_path / "manual.pdf").read_bytes()), "pages": 45,
           "url": "https://manufacturer.example/manual.pdf", "type": "Synthetic manufacturer family manual"}
    write_json(tmp_path / "verification.json", {"documents": [doc]})
    summary = "# Assessment\n\n## Basis\nScreening only, not setup approval.\n\n## Alpha\n1. Operation: turning.\n2. Fit: unknown.\n3. Tooling: unknown.\n4. Limits: conditional.\n5. Still needed: option.\n\n## Hazards\n| UNIT-01 | Conflicting unit pair; not an active limit. |\n"
    (tmp_path / "summary.md").write_text(summary, encoding="utf-8")
    index = {"schemaVersion": "equipment-document-index-v1", "summaryPath": "summary.md", "summarySha256": sha(summary.encode()),
        "verificationPath": "verification.json", "verificationSha256": sha((tmp_path / "verification.json").read_bytes()),
        "bindings": [{"assetId": "asset-alpha", "assetDefinitionRevision": "a" * 64, "model": "Model Alpha",
            "summaryHeading": "Alpha", "hazardIds": ["UNIT-01"], "applicability": "Not Model Beta. Option unknown.", "documents": ["manual.pdf"]}]}
    path = tmp_path / "index.json"
    write_json(path, index)
    return {"reader": EquipmentDocumentLibrary(tmp_path, path), "root": tmp_path, "index": index, "indexPath": path,
            "asset": {"assetId": "asset-alpha", "assetDefinitionRevision": "a" * 64}, "doc": doc}


def request(library, action="summary", **fields):
    args = {**library["asset"], "action": action, **fields}
    if action != "summary":
        args.update(documentId=library["doc"]["file"], documentRevision=library["doc"]["sha256"])
    return args


def failure(code, call):
    with pytest.raises(ResearchError) as caught:
        call()
    assert caught.value.code == code


def test_summary_has_scoped_questions_hazards_and_exact_document(library):
    result = library["reader"].read(request(library))
    assert "5. Still needed" in result["summary"]
    assert "UNIT-01" in result["sourceHazards"][0]
    assert result["documents"][0]["documentRevision"] == library["doc"]["sha256"]
    assert result["productionEligible"] is result["executableConstraints"] is False
    assert result["reviewStatus"] == "pending"
    assert library["reader"].availability(library["asset"])["status"] == "registered"
    library["reader"].validate_result(result)


@pytest.mark.parametrize("value", [None, [], "manual.pdf"])
def test_nonobject_read_is_a_named_error(library, value):
    failure("equipment_document_request_invalid", lambda: library["reader"].read(value))


@pytest.mark.parametrize("changes,code", [
    ({"assetId": "asset-beta"}, "equipment_documents_unregistered"),
    ({"assetDefinitionRevision": "b" * 64}, "equipment_document_asset_stale"),
    ({"path": "manual.pdf"}, "equipment_document_request_invalid"),
    ({"action": "run"}, "equipment_document_request_invalid"),
])
def test_summary_rejects_unbound_or_injected_input(library, changes, code):
    failure(code, lambda: library["reader"].read({**request(library), **changes}))


def test_model_and_revision_do_not_fall_back(library):
    args = request(library, "page", pageNumber=1, textOffset=0)
    failure("equipment_document_model_mismatch", lambda: library["reader"].read({**args, "documentId": "sibling.pdf"}))
    failure("equipment_document_revision_mismatch", lambda: library["reader"].read({**args, "documentRevision": "c" * 64}))
    assert library["reader"].availability({**library["asset"], "assetDefinitionRevision": "b" * 64})["status"] == "stale_binding"


def test_reference_typo_has_a_repair_but_changed_bytes_do_not(library):
    args = request(library, "page", pageNumber=1, textOffset=0)
    with pytest.raises(ResearchError) as caught:
        library["reader"].read({**args, "documentRevision": "c" * 64})
    assert caught.value.details == {"failureKind": "reference_mismatch", "registeredReference": {
        "documentId": library["doc"]["file"], "documentRevision": library["doc"]["sha256"]}}
    fixed = {**args, **caught.value.details["registeredReference"]}
    assert library["reader"].read(fixed)["textStatus"] == "extracted"
    with (library["root"] / "manual.pdf").open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ResearchError) as changed:
        library["reader"].read(fixed)
    assert changed.value.code == "equipment_document_revision_mismatch"
    assert "registeredReference" not in changed.value.details


def test_search_is_paginated_and_scans_do_not_prove_absence(library):
    first = library["reader"].read(request(library, "search", query="Distinctive tooling", startPage=1))
    assert first["matches"] == [] and first["nextPage"] == 41
    assert first["searchComplete"] is False
    second = library["reader"].read(request(library, "search", query="Distinctive tooling", startPage=41))
    assert second["matches"][0]["pageNumber"] == 41
    assert second["pagesWithoutText"] == [45] and second["searchComplete"] is False
    assert second["nextPage"] is None
    many = library["reader"].read(request(library, "search", query="payload", startPage=1))
    assert len(many["matches"]) == 6 and many["nextPage"] == 7


def test_pages_preserve_text_and_offer_bounded_continuation(library, monkeypatch):
    import ai_inspector.research.equipment_documents as module
    monkeypatch.setattr(module, "PAGE_CHARS", 20)
    first = library["reader"].read(request(library, "page", pageNumber=1, textOffset=0))
    assert first["truncated"] and first["nextTextOffset"] == 20
    second = library["reader"].read(request(library, "page", pageNumber=1, textOffset=20))
    assert first["text"] != second["text"] and second["textOffset"] == 20
    assert not first["complete"] and not second["complete"]
    offset = second["nextTextOffset"]
    while offset is not None:
        tail = library["reader"].read(request(library, "page", pageNumber=1, textOffset=offset))
        assert tail["truncated"] and not tail["complete"]
        offset = tail["nextTextOffset"]
    assert first["needsVisualReview"] is True
    blank = library["reader"].read(request(library, "page", pageNumber=45, textOffset=0))
    assert blank["textStatus"] == "no_extractable_text" and blank["complete"] is False


def test_pdf_navigation_is_local_bounded_and_one_based(library, monkeypatch):
    import ai_inspector.research.equipment_documents as module
    monkeypatch.setattr(module, "NAVIGATION_LINKS", 1)
    page = library["reader"].read(request(library, "page", pageNumber=1, textOffset=0))
    assert page["internalPageLinks"] == [{"anchorText": "Model Alpha page 1. Nominal payload 10 kg; option X only.", "targetPageNumber": 41}]
    assert page["navigationTruncated"] is True
    search = library["reader"].read(request(library, "search", query="payload", startPage=1))
    assert search["matches"][0]["internalPageLinks"] == page["internalPageLinks"]
    assert sum(len(hit["internalPageLinks"]) for hit in search["matches"]) == 1
    assert "external.example" not in json.dumps(search)
    target = library["reader"].read(request(library, "page", pageNumber=41, textOffset=0))
    assert "Distinctive tooling" in target["text"]


@pytest.mark.parametrize("fields", [{"pageNumber": 0, "textOffset": 0}, {"pageNumber": 46, "textOffset": 0},
    {"pageNumber": True, "textOffset": 0}, {"pageNumber": 1, "textOffset": -1}, {"pageNumber": 1, "textOffset": 10000}])
def test_invalid_pages_and_offsets(library, fields):
    failure("equipment_document_page_invalid", lambda: library["reader"].read(request(library, "page", **fields)))


@pytest.mark.parametrize("name", ["summary.md", "verification.json", "manual.pdf"])
def test_changed_content_invalidates_read_and_retained_receipt(library, name):
    args = request(library, "page", pageNumber=1, textOffset=0)
    receipt = library["reader"].read(args)
    with (library["root"] / name).open("ab") as stream:
        stream.write(b"changed")
    failure("equipment_document_revision_mismatch", lambda: library["reader"].read(args))
    failure("equipment_document_revision_mismatch", lambda: library["reader"].validate_result(receipt))


def test_no_unregistered_files_and_size_budget(library, monkeypatch):
    library["index"]["summaryPath"] = "../outside.md"
    write_json(library["indexPath"], library["index"])
    failure("equipment_document_path_invalid", lambda: library["reader"].read(request(library)))
    failure("equipment_document_budget_exceeded", lambda: library["reader"]._bytes(library["root"] / "manual.pdf", 10))


def test_normalized_summary_line_endings_and_missing_file(library):
    summary = library["root"] / "summary.md"
    summary.write_bytes(summary.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))
    assert library["reader"].read(request(library))["complete"] is True
    (library["root"] / "manual.pdf").unlink()
    failure("equipment_document_unavailable", lambda: library["reader"].read(request(library, "page", pageNumber=1, textOffset=0)))


@pytest.mark.parametrize("binding", json.loads(INDEX_PATH.read_text())["bindings"], ids=lambda binding: binding["model"])
def test_private_reviewed_documents_are_exact_and_readable(binding):
    reader = EquipmentDocumentLibrary()
    if not (reader.root / "output/pdf/equipment-documents-2026-09-09/verification.json").exists():
        pytest.skip("Private manufacturer collection is not included in source distribution")
    asset = {key: binding[key] for key in ("assetId", "assetDefinitionRevision")}
    summary = reader.read({**asset, "action": "summary"})
    assert all(label in summary["summary"] for label in ("1.", "2.", "3.", "4.", "5."))
    for document in summary["documents"]:
        result = reader.read({**asset, "action": "page", "documentId": document["documentId"],
            "documentRevision": document["documentRevision"], "pageNumber": 1, "textOffset": 0})
        reader.validate_result(result)
        assert result["pageCount"] == document["pageCount"]
        assert result["executableConstraints"] is False
    if binding["model"] == "ACER Dynamic 1760G":
        assert result["textStatus"] == "no_extractable_text"
