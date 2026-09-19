from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import server


def _product_capture() -> bytes:
    image = Image.new("RGB", (2200, 2200), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rounded_rectangle(
        (420, 280, 1780, 1880),
        radius=80,
        fill=(202, 208, 211),
        outline=(55, 70, 78),
        width=12,
    )
    drawing.rectangle((650, 460, 1550, 760), fill=(177, 185, 190))
    drawing.line((700, 1650, 1500, 900), fill=(38, 53, 62), width=18)
    payload = BytesIO()
    image.save(payload, format="PNG")
    return payload.getvalue()


def test_compiler_builds_one_evidence_bound_product_sheet() -> None:
    assembly_data, catalog = server._parts_manual_catalog_for_assembly("MMLE-50D")
    document = server._specification_sheet_base_document(assembly_data, catalog)

    assert document["documentType"] == "product_specification_sheet"
    assert document["status"] == "review_ready"
    assert document["pageCount"] == 1
    assert document["publicationLayout"]["page"] == {
        "width": 612.0,
        "height": 792.0,
        "aspectRatio": 612.0 / 792.0,
        "orientation": "portrait",
        "logicalUnit": "pt",
    }
    page = document["pages"][0]
    assert page["pageType"] == "product_specification"
    assert len(page["specifications"]) == 6
    assert len(page["features"]) == 3
    assert page["renderRequest"]["pose"] == "assembled"
    assert page["renderRequest"]["illustrationStyle"] == "SHADED_COLOR"
    assert page["renderRequest"]["showItemCallouts"] is False
    assert page["renderRequest"]["calloutItems"] == []
    assert document["evidenceSummary"]["approvedClaimCount"] == 9
    assert document["evidenceSummary"]["citedSourceCount"] == 3


def test_live_api_requires_capture_then_exports_one_page_pdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.setattr(server, "SPECIFICATION_SHEET_ROOT", tmp_path / "sheets")
    client = TestClient(server.app)

    types = client.get("/api/documentation/types")
    assert types.status_code == 200
    assert any(
        row["documentType"] == "product_specification_sheet"
        for row in types.json()["documentTypes"]
    )
    descriptor = next(
        row
        for row in types.json()["documentTypes"]
        if row["documentType"] == "product_specification_sheet"
    )
    assert descriptor["supports"]["reviewDocx"] is True
    assert descriptor["supports"]["docx"] is True

    generated = client.post(
        "/api/specification-sheet/MMLE-50D/generate?rebaseline=true"
    )
    assert generated.status_code == 200
    document = generated.json()["document"]
    page = document["pages"][0]

    refused = client.post("/api/specification-sheet/MMLE-50D/pdf")
    assert refused.status_code == 422
    assert refused.json()["error"] == "specification_sheet_capture_required"

    captured = client.post(
        f"/api/specification-sheet/MMLE-50D/document/{page['pageId']}/render",
        data={
            "documentRevision": document["documentRevision"],
            "manualPlanRevision": document["manualPlanRevision"],
            "sourceRevision": document["sourceRevision"],
            "renderPipelineVersion": str(document["renderPipelineVersion"]),
            "balloons": "[]",
        },
        files={"file": ("product.png", _product_capture(), "image/png")},
    )
    assert captured.status_code == 200
    artifact = captured.json()["artifact"]
    assert artifact["status"] == "ready"
    assert artifact["balloons"] == []
    assert artifact["calloutManifestValidated"] is False
    assert "/api/specification-sheet/" in artifact["url"]

    exported = client.post("/api/specification-sheet/MMLE-50D/pdf")
    assert exported.status_code == 200
    result = exported.json()
    assert result["stage"] == "review_exported"
    assert result["pdf"]["pageCount"] == 1
    assert result["pdf"]["controlledRelease"] is False
    assert result["docx"]["pageCount"] == 1
    assert result["docx"]["controlledRelease"] is False
    assert result["docx"]["documentRevision"] == result["pdf"]["documentRevision"]
    assert result["docx"]["rendererVersion"] == "specification-sheet-docx-v1"

    downloaded = client.get(result["pdf"]["url"])
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF")
    import fitz

    pdf = fitz.open(stream=downloaded.content, filetype="pdf")
    try:
        assert pdf.page_count == 1
        text = pdf[0].get_text()
        assert "MMLE-50D Electric Mobile Lift" in text
        assert "Specifications" in text
        assert "1,100 lb" in text
        assert "REVIEW" in text
    finally:
        pdf.close()

    editable_download = client.get(result["docx"]["url"])
    assert editable_download.status_code == 200
    assert editable_download.content.startswith(b"PK")
    from docx import Document
    from docx.enum.section import WD_ORIENT

    editable = Document(BytesIO(editable_download.content))
    assert editable.sections[0].orientation == WD_ORIENT.PORTRAIT
    editable_text = "\n".join(
        [paragraph.text for paragraph in editable.paragraphs]
        + [cell.text for table in editable.tables for row in table.rows for cell in row.cells]
    )
    assert "MMLE-50D Electric Mobile Lift" in editable_text
    assert "Specifications" in editable_text
    assert "1,100 lb" in editable_text
    assert len(editable.inline_shapes) == 1


def test_sage_routes_specification_sheet_separately_from_manuals() -> None:
    request = server.AgentChatRequest(
        message="generate a specification sheet",
        agent_type="inspector",
    )
    generated = server._deterministic_documentation_chat_result(request)
    assert generated is not None
    assert generated["tool_calls"] == [
        {"name": "generate_specification_sheet_draft", "args": {}}
    ]
    assert generated["documentation_command"]["documentType"] == (
        "product_specification_sheet"
    )

    published = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="publish the spec sheet PDF without opening it",
            agent_type="inspector",
        )
    )
    assert published is not None
    assert published["tool_calls"] == [
        {
            "name": "publish_specification_sheet",
            "args": {"open_pdf": False, "open_docx": False},
        }
    ]

    docx_publication = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="export the specification sheet Word document",
            agent_type="inspector",
        )
    )
    assert docx_publication is not None
    assert docx_publication["tool_calls"] == [
        {
            "name": "publish_specification_sheet",
            "args": {"open_pdf": False, "open_docx": True},
        }
    ]

    selected = server.AgentChatRequest(
        message="generate this sheet",
        agent_type="inspector",
        context={
            "attachments": {
                "documentation": {
                    "document_type": "product_specification_sheet",
                }
            }
        },
    )
    selected_result = server._deterministic_documentation_chat_result(selected)
    assert selected_result is not None
    assert selected_result["tool_calls"][0]["name"] == (
        "generate_specification_sheet_draft"
    )


def test_frontend_contains_blank_reveal_capture_and_publish_paths() -> None:
    source = Path("static/index.html").read_text("utf-8")
    assert "_documentationGenerateSpecificationSheetBaseline" in source
    assert "product_specification_sheet" in source
    assert "Specification Sheet | Live CAD capture" in source
    assert "Neutral Shaded CAD" in source
    assert "generate_specification_sheet_draft" in source
    assert "publish_specification_sheet" in source
    assert "/api/specification-sheet/${encodeURIComponent(" in source
    assert "reviewDocx: exported.docx" in source


def test_documentation_type_selector_uses_supplied_theme_icons() -> None:
    source = Path("static/index.html").read_text("utf-8")
    asset_root = Path("static/assets/documentation-type-icons")
    icon_names = {
        "illustrated_parts_manual": "parts_manual.svg",
        "operations_and_maintenance_manual": "operations_manual.svg",
        "product_specification_sheet": "specification_sheet.svg",
        "work_instructions": "instructions.svg",
        "inspection_sheet": "inspection_sheet.svg",
    }

    assert "_documentationCreateDocumentTypeSelector" in source
    assert 'id = \'documentationTypeRibbonTrigger\'' in source
    assert 'id = \'documentationTypeRibbonListbox\'' in source
    assert 'id = \'documentationTypeRibbonSelect\'' in source
    assert "DOCUMENTATION_DOCUMENT_TYPES" in source
    assert "workflow-type-icon-${theme}" in source
    assert "/static/assets/documentation-type-icons/${theme}/${type.icon}" in source

    for document_type, icon_name in icon_names.items():
        assert document_type in source
        assert icon_name in source
        for theme in ("light", "dark"):
            icon_path = asset_root / theme / icon_name
            assert icon_path.is_file(), f"Missing {theme} icon: {icon_path}"
