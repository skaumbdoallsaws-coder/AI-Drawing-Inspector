from __future__ import annotations

import copy
import hashlib
import json
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

import server
from ai_inspector.operations_manual.artifacts import (
    OperationsManualArtifactError, attach_draft_render_artifacts, document_draft_render_path,
    store_draft_render_artifact,
)
from ai_inspector.work_instructions.document import WorkInstructionError, page_figure_revision, with_figure_revisions
from ai_inspector.work_instructions.exports import review_export_readiness


def _technical_capture() -> bytes:
    image = Image.new("RGB", (1920, 1080), "white")
    drawing = ImageDraw.Draw(image)
    drawing.rectangle(
        (260, 160, 1660, 900),
        fill=(238, 241, 243),
        outline=(31, 53, 66),
        width=8,
    )
    drawing.line((400, 780, 850, 320, 1450, 720), fill=(36, 55, 66), width=12)
    payload = BytesIO()
    image.save(payload, format="PNG")
    return payload.getvalue()


def test_compiler_preserves_the_complete_assumed_process_baseline() -> None:
    assembly_data, catalog = server._parts_manual_catalog_for_assembly("MMLE-50D")
    document = server._work_instruction_base_document(assembly_data, catalog)

    assert document["documentType"] == "work_instructions"
    assert document["status"] == "prototype_ready"
    assert document["statusLabel"] == "PROTOTYPE BASELINE"
    assert document["pageCount"] == 20
    assert document["publicationLayout"]["page"] == {
        "width": 960.0,
        "height": 540.0,
        "aspectRatio": 16 / 9,
        "orientation": "landscape",
        "logicalUnit": "pt",
    }

    plan = document["workInstructionPlan"]
    assert plan["planStatus"] == "prototype_baseline_assumed"
    assert plan["approvalAssumption"] == {
        "status": "assumed_for_prototype",
        "basis": "explicit_user_direction",
        "manufacturingApproval": False,
        "controlledReleaseAuthority": False,
    }
    assert plan["summary"]["stageCount"] == 14
    assert plan["summary"]["operationCount"] == 79
    assert plan["summary"]["requiredOccurrenceCount"] == 206
    assert plan["summary"]["coveredOccurrenceCount"] == 206
    assert plan["sourceBinding"]["occurrenceBindingCount"] == 206
    assert plan["sourceBinding"]["allRequiredOccurrencesResolved"] is True

    operation_ids = [
        operation["stepId"]
        for stage in plan["stages"]
        for operation in stage["operations"]
    ]
    assert len(operation_ids) == 79
    assert len(set(operation_ids)) == 79

    figure_pages = [page for page in document["pages"] if page.get("renderRequest")]
    assert len(figure_pages) == 18
    stage_pages = {
        page["sectionId"]: page
        for page in document["pages"]
        if page.get("pageType") == "work_instruction_stage"
    }
    final_page = stage_pages["op-final-release"]
    assert "renderRequest" not in final_page
    assert all(
        block.get("blockType") != "cad_figure"
        for block in final_page["layoutBlocks"]
    )
    assert plan["stages"][-1]["title"] == (
        "Review records and close demonstration build"
    )

    benchmark = next(
        stage["instructionBenchmark"]
        for stage in plan["stages"]
        if stage["stageId"] == "op-build-lift-mechanism"
    )
    assert benchmark["benchmarkStatus"] == "approved_for_synthetic_demonstration"
    assert benchmark["authorization"]["manufacturingApproval"] is False
    assert benchmark["authorization"]["controlledReleaseAuthority"] is False
    assert len(benchmark["operationPages"]) == 5
    operation_pages = [
        page
        for page in document["pages"]
        if page.get("pageType") == "work_instruction_operation"
    ]
    assert [page["title"].split(" - ", 1)[0] for page in operation_pages] == [
        "Step 03A",
        "Step 03B",
        "Step 03C",
        "Step 03D",
        "Step 03E",
    ]
    assert all(
        {
            "DO - OPERATOR ACTIONS",
            "TOOLS / MATERIALS / KEY POINTS",
            "SPECIFICATION",
            "VERIFY / RECORD",
        }
        <= {
            str(block.get("text") or "")
            for block in page.get("layoutBlocks") or []
        }
        for page in operation_pages
    )
    assert [page["renderRequest"]["cameraPreset"] for page in operation_pages] == [
        "front",
        "right",
        "isometric",
        "top",
        "right",
    ]
    assert [page["renderRequest"]["pose"] for page in operation_pages] == [
        "exploded",
        "exploded",
        "exploded",
        "exploded",
        "assembled",
    ]
    assert len({page["pageId"] for page in operation_pages}) == 5
    assert len(
        {
            (
                tuple(page["renderRequest"]["occurrenceIds"]),
                tuple(page["renderRequest"]["focusOccurrenceIds"]),
                page["renderRequest"]["cameraPreset"],
                page["renderRequest"]["pose"],
                page["renderRequest"]["explodeFactor"],
            )
            for page in operation_pages
        }
    ) == 5
    assert all(page["renderRequest"]["calloutItems"] for page in operation_pages)
    assert all(
        page["instructionOperation"]["evidenceBinding"]["benchmarkHash"]
        for page in operation_pages
    )
    assert all(
        page["instructionOperation"]["evidenceBinding"]["documentId"]
        == "SYN-MMLE-WI-LIFT-001"
        for page in operation_pages
    )
    assert [
        len(page["instructionOperation"]["resolvedParts"])
        for page in operation_pages
    ] == [2, 4, 4, 8, 4]
    assert [
        len(page["renderRequest"]["calloutItems"])
        for page in operation_pages
    ] == [2, 4, 4, 6, 4]

    integration_pages = [
        next(
            page
            for page in document["pages"]
            if page.get("sectionId") == stage["stageId"]
        )
        for stage in plan["stages"]
        if 8 <= int(stage["sequenceNumber"]) <= 13
    ]
    assert all(
        page["renderRequest"]["showItemCallouts"]
        and page["renderRequest"]["calloutItems"]
        for page in integration_pages
    )
    assert len(integration_pages[0]["renderRequest"]["calloutItems"]) == 5
    assert all(
        len(page["renderRequest"]["calloutItems"]) == 3
        for page in integration_pages[1:3]
    )
    assert all(
        len(page["renderRequest"]["calloutItems"]) == 2
        for page in integration_pages[3:]
    )
    electrical_targets = [
        item["description"]
        for item in stage_pages["op-install-electrical-controls"]["renderRequest"][
            "calloutItems"
        ]
    ]
    assert electrical_targets == ["Battery", "Battery Box"]
    assert [
        item["description"]
        for item in stage_pages["op-in-process-inspection"]["renderRequest"][
            "calloutItems"
        ]
    ] == ["Anchor Plate", "Channel"]
    assert [
        item["description"]
        for item in stage_pages["op-functional-test"]["renderRequest"][
            "calloutItems"
        ]
    ] == ["Cylinder Barrel", "Inner Scissor Arm"]
    assert len(
        {
            page["renderRequest"]["cameraPreset"]
            for page in integration_pages[-3:]
        }
    ) == 3
    assert all(page["renderRequest"]["focusOccurrenceIds"] for page in integration_pages)

    visible_text = "\n".join(
        str(block.get("text") or "")
        for page in document["pages"]
        for block in page.get("layoutBlocks") or []
    )
    assert "more item types" not in visible_text
    assert "Components in view" not in visible_text
    assert "modeled" not in visible_text.casefold()
    plan_action_text = "\n".join(
        str(operation.get("action") or "")
        for stage in plan["stages"]
        for operation in stage["operations"]
    )
    for leaked_phrase in (
        "without inventing",
        "without applying an unsupported",
        "does not establish production acceptance",
        "without converting them into production dispositions",
    ):
        assert leaked_phrase not in plan_action_text.casefold()
    assert "HOLD - Approved wire-routing specifications" in plan_action_text
    assert "ENGINEERING REVIEW REQUIRED" in plan_action_text
    for held_stage_id in ("op-build-battery-controls", "op-functional-test"):
        held_panel = next(
            block
            for block in stage_pages[held_stage_id]["layoutBlocks"]
            if block.get("blockId") == f"{held_stage_id}-components"
        )
        assert held_panel["blockType"] == "status_panel"
        assert held_panel["signalWord"] == "NOTICE"
        assert held_panel["text"].startswith("ENGINEERING DATA REQUIRED -")
    assert all(
        "modeled" not in str(operation.get("action") or "").casefold()
        for stage in plan["stages"]
        for operation in stage["operations"]
    )

    mounted_check = next(
        block["text"]
        for block in stage_pages["op-install-lift-and-platform"]["layoutBlocks"]
        if block.get("blockId") == "op-install-lift-and-platform-quality"
    )
    mechanism_check = next(
        block["text"]
        for block in operation_pages[-1]["layoutBlocks"]
        if block.get("blockId") == "wi-lift-03e-quality"
    )
    assert "three complete unpowered cycles" in mechanism_check.casefold()
    assert "mobile-base interfaces" in mounted_check
    assert mounted_check != mechanism_check

    benchmark_text = "\n".join(
        str(block.get("text") or "")
        for page in operation_pages
        for block in page.get("layoutBlocks") or []
    )
    assert "44 +/- 4 N m" in benchmark_text
    assert "210 +/- 10 N m" in benchmark_text
    assert "0.20-0.50 mm" in benchmark_text
    assert "SYN-MMLE-WI-LIFT-001 Rev A" in benchmark_text
    assert "SYN-FRM-WI-003E" in benchmark_text
    exit_gate = operation_pages[-1]["instructionOperation"]["transitionGate"]
    assert exit_gate == {
        "gateId": "SYN-GATE-WI-003E",
        "targetStageOperationId": "op-install-lift-and-platform",
        "requiredCheckIds": [
            "SYN-QC-03E-01",
            "SYN-QC-03E-02",
            "SYN-QC-03E-03",
        ],
        "requiredRecordId": "SYN-FRM-WI-003E",
        "satisfiedState": "eligible_for_main_integration",
        "failureState": "hold_for_engineering_review",
        "blocking": True,
    }
    assert "HOLD FOR ENGINEERING REVIEW" in mechanism_check
    sequence_page = next(
        page
        for page in document["pages"]
        if page.get("pageType") == "work_instruction_sequence"
    )
    sequence_text = "\n".join(
        str(block.get("text") or "")
        for block in sequence_page["layoutBlocks"]
    )
    assert "VALIDATED INSTRUCTION COVERAGE" in sequence_text
    assert "RELEASE BLOCKERS" in sequence_text
    assert "Only Stage 03 has detailed evidence-bound coverage" in sequence_text

    release_codes = {
        row["code"] for row in document["releaseGate"]["findings"]
    }
    assert {
        "MISSING_APPROVED_TORQUE_REQUIREMENTS",
        "MISSING_APPROVED_TEST_LIMITS",
        "MISSING_APPROVED_SAFETY_CONTROLS",
        "SYNTHETIC_BENCHMARK_SPECIFICATIONS",
    } <= release_codes
    assert document["releaseGate"]["reviewPdfAllowed"] is True
    assert document["releaseGate"]["controlledPdfAllowed"] is False
    assert document["releaseGate"]["controlledReleaseStatus"] == "BLOCKED"
    assert document["releaseGate"]["assumedPlanAccepted"] is True
    coverage = document["releaseGate"]["coverage"]
    assert coverage["validatedBenchmarkStageIds"] == ["op-build-lift-mechanism"]
    assert coverage["validatedBenchmarkOperationPageCount"] == 5
    assert len(coverage["processPlanOnlyStageIds"]) == 13
    assert "op-build-lift-mechanism" not in coverage["processPlanOnlyStageIds"]
    assert coverage["controlledReleaseBlocked"] is True


def test_live_api_refuses_uncaptured_export_then_builds_landscape_review_pdf(
    tmp_path: Path,
    monkeypatch,
) -> None:
    root = tmp_path / "work-instructions"
    monkeypatch.setattr(server, "WORK_INSTRUCTION_ROOT", root)
    client = TestClient(server.app)

    types = client.get("/api/documentation/types")
    assert types.status_code == 200
    descriptor = next(
        row
        for row in types.json()["documentTypes"]
        if row["documentType"] == "work_instructions"
    )
    assert descriptor["status"] == "review_available"
    assert descriptor["pageOrientation"] == "landscape"
    assert descriptor["supports"]["reviewPdf"] is True
    assert descriptor["supports"]["reviewDocx"] is True
    assert descriptor["supports"]["docx"] is True

    context = client.get("/api/work-instructions/MMLE-50D")
    assert context.status_code == 200
    assert context.json()["draftReady"] is True
    plan_summary = context.json()["planSummary"]
    assert plan_summary["stageCount"] == 14
    assert plan_summary["operationCount"] == 79
    assert plan_summary["requiredOccurrenceCount"] == 206
    assert plan_summary["coveredOccurrenceCount"] == 206
    assert plan_summary["resourceCount"] == 8
    assert plan_summary["requirementCount"] == 13

    generated = client.post(
        "/api/work-instructions/MMLE-50D/generate?rebaseline=true"
    )
    assert generated.status_code == 200
    document = generated.json()["document"]
    assert document["pageCount"] == 20

    refused = client.post("/api/work-instructions/MMLE-50D/pdf")
    assert refused.status_code == 422
    assert refused.json()["error"] == "work_instruction_capture_required"
    assert refused.json()["requiredCaptureCount"] == 18

    payload = _technical_capture()
    for page in document["pages"]:
        if not page.get("renderRequest"):
            continue
        store_draft_render_artifact(
            root,
            "MMLE-50D",
            document,
            page["pageId"],
            payload,
            source_revision=document["sourceRevision"],
            manual_plan_revision=document["manualPlanRevision"],
            api_route="work-instructions",
        )

    exported = client.post("/api/work-instructions/MMLE-50D/pdf")
    assert exported.status_code == 200, exported.text
    result = exported.json()
    assert result["stage"] == "prototype_review_exported"
    assert result["pdf"]["controlledRelease"] is False
    assert result["pdf"]["pageCount"] == 20
    assert "/api/work-instructions/" in result["pdf"]["url"]
    assert result["docx"]["controlledRelease"] is False
    assert result["docx"]["pageCount"] == 20
    assert result["docx"]["documentRevision"] == result["pdf"]["documentRevision"]
    assert result["docx"]["rendererVersion"] == "work-instructions-docx-rich-v2"

    downloaded = client.get(result["pdf"]["url"])
    assert downloaded.status_code == 200
    assert downloaded.content.startswith(b"%PDF")
    import fitz

    pdf = fitz.open(stream=downloaded.content, filetype="pdf")
    try:
        assert pdf.page_count == 20
        assert pdf[0].rect.width == 960.0
        assert pdf[0].rect.height == 540.0
        text = "\n".join(page.get_text() for page in pdf).upper()
        assert "ASSEMBLY WORK INSTRUCTIONS" in text
        assert "PROTOTYPE BASELINE" in text
        assert "ASSEMBLY SEQUENCE" in text
        assert "MANUFACTURING APPROVAL" in text
        assert "44 +/- 4 N M" in text
        assert "210 +/- 10 N M" in text
        assert "SYN-MMLE-WI-LIFT-001 REV A" in text
        assert "VALIDATED INSTRUCTION COVERAGE" in text
        assert "RELEASE BLOCKERS" in text
        assert "HOLD FOR ENGINEERING REVIEW" in text
        assert "WITHOUT INVENTING" not in text
    finally:
        pdf.close()

    editable_download = client.get(result["docx"]["url"])
    assert editable_download.status_code == 200
    assert editable_download.content.startswith(b"PK")
    from docx import Document
    from docx.enum.section import WD_ORIENT

    editable = Document(BytesIO(editable_download.content))
    assert editable.sections[0].orientation == WD_ORIENT.LANDSCAPE
    editable_text = "\n".join(
        paragraph.text for paragraph in editable.paragraphs
    ).upper()
    assert "ASSEMBLY WORK INSTRUCTIONS" in editable_text
    assert "PROTOTYPE BASELINE" in editable_text
    assert "44 +/- 4 N M" in editable_text
    assert len(editable.inline_shapes) >= 10


def test_sage_routes_work_instructions_without_confusing_other_manuals() -> None:
    generated = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="generate assembly work instructions",
            agent_type="inspector",
        )
    )
    assert generated is not None
    assert generated["tool_calls"] == [
        {"name": "generate_work_instructions_draft", "args": {}}
    ]
    assert generated["documentation_command"]["documentType"] == "work_instructions"
    assert "not manufacturing approval" in generated["response"]

    exported = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="export the work instruction PDF without opening it",
            agent_type="inspector",
        )
    )
    assert exported is not None
    assert exported["tool_calls"] == [
        {
            "name": "publish_work_instructions",
            "args": {"open_pdf": False, "open_docx": False},
        }
    ]

    docx_export = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="export the work instruction DOCX",
            agent_type="inspector",
        )
    )
    assert docx_export is not None
    assert docx_export["tool_calls"] == [
        {
            "name": "publish_work_instructions",
            "args": {"open_pdf": False, "open_docx": True},
        }
    ]

    visible_workflow = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="generate this manual",
            agent_type="inspector",
            context={
                "attachments": {
                    "documentation": {"document_type": "work_instructions"}
                }
            },
        )
    )
    assert visible_workflow is not None
    assert visible_workflow["tool_calls"][0]["name"] == (
        "generate_work_instructions_draft"
    )

    question = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="what evidence do the work instructions use?",
            agent_type="inspector",
        )
    )
    assert question is None
    route = server._safe_parts_manual_route("build work instructions")
    assert route["intents"][0]["kind"] == "generate_work_instructions"
    assert route["intents"][0]["targets"] == [
        {"kind": "work_instructions", "id": None}
    ]


def test_frontend_wires_blank_reveal_live_capture_and_fresh_export() -> None:
    source = Path("static/index.html").read_text("utf-8")

    assert "_documentationGenerateWorkInstructionsBaseline" in source
    assert "work_instructions" in source
    assert "Work Instructions | Live CAD capture" in source
    assert "work_instruction_plan_bound" in source
    assert "forceFigureCapture: true" in source
    assert "generate_work_instructions_draft" in source
    assert "publish_work_instructions" in source
    assert "_documentationWorkInstructionsReceipt" in source
    assert "_workInstructionsSemanticToolStatusLine" in source
    assert "/api/work-instructions/${encodeURIComponent(" in source
    assert "Capturing ${pending.length} missing or stale instruction figure" in source
    assert "pages: pending" in source
    assert "reviewDocx: exported.docx" in source
    assert "state.partsManualPayload?.assemblyNumber || assemblyNumber" in source
    assert "const captureAssemblyNumber = String(" in source
    assert "+ `/${encodeURIComponent(captureAssemblyNumber)}`" in source
    assert "_partsManualCreateItemCallouts(payload, section, groups);" in source


def _stored_bytes(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob("*") if path.is_file()}


def _figure_pages(document):
    return {page["pageId"]: page for page in document["pages"] if page.get("renderRequest")}


def _edit_cover(client, state, text="Edited instruction note."):
    document = state["document"]
    response = client.post("/api/work-instructions/MMLE-50D/documentation-scene/commands", json={
        "baseRevision": state["revision"], "sourceRevision": document["sourceRevision"],
        "manualPlanRevision": document["manualPlanRevision"], "operation": "update_text",
        "pageId": "page-work-instructions-cover", "targetType": "page_element",
        "targetId": "wi-cover-status", "text": text,
    })
    assert response.status_code == 200, response.text
    return response.json()


def test_a_text_edit_keeps_the_figures_captured_and_a_figure_edit_does_not(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "wi"
    monkeypatch.setattr(server, "WORK_INSTRUCTION_ROOT", root)
    client = TestClient(server.app)
    base = "/api/work-instructions/MMLE-50D"
    state = client.get(base + "/documentation-scene").json()
    document = state["document"]
    assert document["schemaVersion"] == 3
    figures = _figure_pages(document)
    capture = _technical_capture()
    for page_id, page in figures.items():
        # The additive figure_revision input is optional for existing callers.
        artifact = store_draft_render_artifact(
            root, "MMLE-50D", document, page_id, capture,
            source_revision=document["sourceRevision"], manual_plan_revision=document["manualPlanRevision"],
            api_route="work-instructions",
        )
        assert artifact["figureRevision"] == page["figureRevision"]
        assert page["figureRevision"] in artifact["url"]
    captures_before = _stored_bytes(root / "mmle-50d" / "renders")
    edited = _edit_cover(client, state)
    after = edited["document"]
    assert after["documentRevision"] != document["documentRevision"]
    assert {key: page["figureRevision"] for key, page in _figure_pages(after).items()} == {
        key: page["figureRevision"] for key, page in figures.items()}
    cover = _figure_pages(after)["page-work-instructions-cover"]
    assert cover["documentationComposition"]["pageElementOverrides"]["wi-cover-status"]["text"] == (
        "Edited instruction note.")
    assert "pageElementOverrides" not in cover["renderRequest"]["composition"]
    for page in _figure_pages(after).values():
        image = page["renderRequest"]["image"]
        assert image["status"] == "ready"
        assert image["documentRevision"] == after["documentRevision"]
        assert image["figureRevision"] == page["figureRevision"]
        assert client.get(image["url"]).content == capture
    assert review_export_readiness(after)["status"] == "READY"
    assert _stored_bytes(root / "mmle-50d" / "renders") == captures_before
    reopened = client.get(base + "/document").json()["document"]
    assert reopened == after

    exported = client.post(base + "/pdf")
    assert exported.status_code == 200, exported.text
    result = exported.json()
    pdf_bytes = client.get(result["pdf"]["url"]).content
    docx_bytes = client.get(result["docx"]["url"]).content
    assert result["pdf"]["documentRevision"] == result["docx"]["documentRevision"] == after["documentRevision"]
    import fitz
    from docx import Document

    with fitz.open(stream=pdf_bytes, filetype="pdf") as pdf:
        assert "Edited instruction note." in pdf[0].get_text()
    # The DOCX exports from the same revision without a recapture. Its text is not checked here: the work-instruction
    # DOCX never carries the cover status line (a P0 finding owned by P4's export fidelity gate, not by this slice).
    assert Document(BytesIO(docx_bytes)).paragraphs
    assert _stored_bytes(root / "mmle-50d" / "renders") == captures_before

    changed = client.post(base + "/documentation-scene/commands", json={
        "baseRevision": edited["revision"], "sourceRevision": after["sourceRevision"],
        "manualPlanRevision": after["manualPlanRevision"], "operation": "set_view",
        "pageId": cover["pageId"], "targetType": "figure", "cameraPreset": "right",
    })
    assert changed.status_code == 200, changed.text
    changed_document = changed.json()["document"]
    changed_figures = _figure_pages(changed_document)
    assert changed_figures[cover["pageId"]]["figureRevision"] != cover["figureRevision"]
    assert changed_figures[cover["pageId"]]["renderRequest"]["composition"]["figureOverride"] == {
        "cameraPreset": "right"}
    for page_id, page in changed_figures.items():
        if page_id != cover["pageId"]:
            assert page["figureRevision"] == figures[page_id]["figureRevision"]
            assert page["renderRequest"]["image"]["status"] == "ready"
    refused = client.post(base + "/pdf")
    assert refused.status_code == 422
    assert refused.json()["error"] == "work_instruction_capture_required"
    assert [page["pageId"] for page in refused.json()["pendingPages"]] == [cover["pageId"]]

    capture_data = {
        "documentRevision": changed_document["documentRevision"],
        "sourceRevision": changed_document["sourceRevision"],
        "manualPlanRevision": changed_document["manualPlanRevision"],
        "renderPipelineVersion": str(changed_document["renderPipelineVersion"]), "balloons": "[]",
    }
    capture_url = base + f"/document/{cover['pageId']}/render"
    files = {"file": ("figure.png", capture, "image/png")}
    stale = client.post(capture_url, data={**capture_data, "figureRevision": cover["figureRevision"]}, files=files)
    assert stale.status_code == 422
    assert "figure revision is stale" in stale.json()["message"]
    stale_legacy = client.post(capture_url, data={**capture_data, "documentRevision": after["documentRevision"]}, files=files)
    assert stale_legacy.status_code == 422
    # Existing clients omit figureRevision and still capture the current document.
    fresh = client.post(capture_url, data=capture_data, files=files)
    assert fresh.status_code == 200, fresh.text
    assert fresh.json()["artifact"]["figureRevision"] == changed_figures[cover["pageId"]]["figureRevision"]
    assert client.post(base + "/pdf").status_code == 200


def _schema_one_document(document):
    # Reproduce the old compiler's shape and canonical hash independently of the
    # migration helper: full composition in renderRequest, no figureRevision.
    def historical(value):
        if isinstance(value, list):
            return [historical(item) for item in value]
        if isinstance(value, dict):
            return {key: historical(item) for key, item in value.items() if key not in {
                "fieldMeta", "provenanceTargets", "provenance", "originalEvidence",
                "activeEvidenceClaimIds", "activeSourceIds", "sourceSupport", "sourceSupportSummary",
                "identityVersion", "aliasMap", "aliasRevision", "identities", "identityOrphans",
                "identityOverrides", "stableId", "rowId", "cellIds", "columnIds", "itemId",
                "identityStatus", "identityScope", "identitySourceKey", "identityCellFields", "sourceKey", "columnKeys", "bomColumnIds", "legacyDocumentationSceneRevision"}}
        return value

    old = historical(document)
    if document.get("legacyDocumentationSceneRevision"):
        old["documentationSceneRevision"] = document["legacyDocumentationSceneRevision"]
    old["schemaVersion"] = 1
    old.pop("documentRevision")
    for page in old["pages"]:
        page.pop("figureRevision", None)
        if page.get("renderRequest"):
            page["renderRequest"]["composition"] = copy.deepcopy(page["documentationComposition"])
    old["documentRevision"] = hashlib.sha256(json.dumps(
        old, ensure_ascii=True, sort_keys=True, separators=(",", ":"), allow_nan=False,
    ).encode("ascii")).hexdigest()
    return old


@pytest.mark.parametrize("actor", ["workspace", "sage"])
def test_legacy_work_instruction_capture_opens_unchanged(tmp_path: Path, monkeypatch, actor) -> None:
    root = tmp_path / "wi"
    monkeypatch.setattr(server, "WORK_INSTRUCTION_ROOT", root)
    client = TestClient(server.app)
    base = "/api/work-instructions/MMLE-50D"
    state = client.get(base + "/documentation-scene").json()
    old = _schema_one_document(state["document"])
    capture = _technical_capture()
    for page_id in _figure_pages(old):
        artifact = store_draft_render_artifact(
            root, "MMLE-50D", old, page_id, capture,
            source_revision=old["sourceRevision"], manual_plan_revision=old["manualPlanRevision"],
            api_route="work-instructions",
        )
        assert "figureRevision" not in artifact
    fixture = root / "old-document.json"
    fixture.write_text(json.dumps(old), encoding="ascii", newline="\n")
    before = _stored_bytes(root)
    loaded = attach_draft_render_artifacts(root, "MMLE-50D", json.loads(fixture.read_text(encoding="ascii")))
    assert loaded["schemaVersion"] == 3
    assert loaded["documentRevision"] == old["documentRevision"]
    assert review_export_readiness(loaded)["status"] == "READY"
    reopened_state = client.get(base + "/documentation-scene").json()
    reopened = reopened_state["document"]
    for page in _figure_pages(reopened).values():
        image = page["renderRequest"]["image"]
        assert image["status"] == "ready"
        assert image["figureRevision"] == page["figureRevision"]
        assert image["captureRevision"] == old["documentRevision"]
        assert image["documentRevision"] == reopened["documentRevision"]
        assert document_draft_render_path(root, "MMLE-50D", reopened, page).read_bytes() == capture
    assert _stored_bytes(root) == before
    assert old == json.loads(fixture.read_text(encoding="ascii"))

    # Keeping an old documentRevision cannot authorize a changed CAD request.
    stale = copy.deepcopy(old)
    stale_page = next(iter(_figure_pages(stale).values()))
    stale_page["renderRequest"]["composition"]["figureOverride"] = {"cameraPreset": "right"}
    stale_page["documentationComposition"]["figureOverride"] = {"cameraPreset": "right"}
    rejected = attach_draft_render_artifacts(root, "MMLE-50D", stale)
    assert all(page["renderRequest"]["image"]["status"] == "pending" for page in _figure_pages(rejected).values())
    assert _stored_bytes(root) == before

    if actor == "workspace":
        edited = _edit_cover(client, reopened_state)["document"]
    else:
        from ai_inspector.documentation.targets import ReadBindings, read_targets

        host = server._DocumentationAgentHost()
        edits = [{"pageId": "page-work-instructions-cover", "targetId": "wi-cover-status",
                  "text": "Edited instruction note."}]
        snapshot = host.document_snapshot("MMLE-50D", "work_instructions")
        bindings = ReadBindings("legacy-work-instruction-edit")
        bindings.record("work_instructions", read_targets(snapshot["state"], snapshot["targets"], edits))
        observed = bindings.bind("work_instructions", {"edits": edits})
        receipt = host.edit_document_text("MMLE-50D", "work_instructions", edits, observed=observed)["receipt"]
        assert receipt["changedIds"]
        edited = client.get(base + "/document").json()["document"]
    assert edited["documentRevision"] != reopened["documentRevision"]
    assert review_export_readiness(edited)["status"] == "READY"
    for page in _figure_pages(edited).values():
        assert page["renderRequest"]["image"]["captureRevision"] == page["figureRevision"]
        assert (root / "mmle-50d" / "renders" / page["figureRevision"] / f"{page['pageId']}.json").is_file()
    # Adoption creates figure-addressed artifacts without modifying legacy bytes.
    assert all((root / name).read_bytes() == value for name, value in before.items())
    after = _stored_bytes(root)
    assert client.get(base + "/document").json()["document"] == edited
    assert _stored_bytes(root) == after


@pytest.mark.parametrize("key,value", [
    ("pose", "exploded"), ("cameraPreset", "right"),
    ("occurrenceIds", ["different-occurrence"]), ("explodeFactor", 0.95),
    ("calloutItems", [{"itemNumber": 99, "occurrenceIds": ["other"]}]),
    ("composition", {"occurrenceOverrides": {"part": {"hidden": True, "translation": [1, 0, 0]}}}),
    ("composition", {"balloonOverrides": {"1": {"translation": [0.1, 0.2]}}}),
    ("composition", {"leaderOverrides": {"1": {"endCondition": "arrow"}}}),
    ("image", {"minimumWidthPx": 3000, "targetAspectRatio": 2.0}),
])
def test_work_instruction_figure_identity_covers_capture_inputs(key, value) -> None:
    document = {"schemaVersion": 2, "sourceRevision": "source", "manualPlanRevision": "plan",
                "renderPipelineVersion": 2, "product": {"assemblyNumber": "TEST"}}
    page = {"pageId": "page", "renderRequest": {"pose": "assembled", "cameraPreset": "isometric",
            "image": {"status": "pending", "minimumWidthPx": 2400}, "composition": {}}}
    before = page_figure_revision(document, page)
    changed = copy.deepcopy(page)
    changed["renderRequest"][key] = value
    assert page_figure_revision(document, changed) != before
    text_only = copy.deepcopy(page)
    text_only["renderRequest"]["composition"] = {
        "pageElementOverrides": {"paragraph": {"text": "New words", "style": {"fontSize": 20}}},
        "documentObjects": {"note": {"text": "New note"}},
    }
    assert page_figure_revision(document, text_only) == before
    for binding in ("sourceRevision", "manualPlanRevision", "renderPipelineVersion"):
        assert page_figure_revision({**document, binding: "changed"}, page) != before
    with pytest.raises(WorkInstructionError, match="unsupported work-instruction document schema"):
        with_figure_revisions({**document, "schemaVersion": 999, "pages": [page]})


def test_work_instruction_capture_accepts_an_unchanged_figure_after_text_edit(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(server, "WORK_INSTRUCTION_ROOT", tmp_path / "wi")
    client = TestClient(server.app)
    base = "/api/work-instructions/MMLE-50D"
    state = client.get(base + "/documentation-scene").json()
    before = state["document"]
    cover = _figure_pages(before)["page-work-instructions-cover"]
    after = _edit_cover(client, state)["document"]
    response = client.post(base + f"/document/{cover['pageId']}/render", data={
        "documentRevision": before["documentRevision"], "figureRevision": cover["figureRevision"],
        "sourceRevision": before["sourceRevision"], "manualPlanRevision": before["manualPlanRevision"],
        "renderPipelineVersion": str(before["renderPipelineVersion"]), "balloons": "[]",
    }, files={"file": ("figure.png", _technical_capture(), "image/png")})
    assert response.status_code == 200, response.text
    assert response.json()["artifact"]["documentRevision"] == after["documentRevision"]
    assert response.json()["artifact"]["figureRevision"] == cover["figureRevision"]


def test_work_instruction_capture_rejects_tampered_bindings_without_writing(tmp_path: Path, monkeypatch) -> None:
    root = tmp_path / "wi"
    monkeypatch.setattr(server, "WORK_INSTRUCTION_ROOT", root)
    client = TestClient(server.app)
    document = client.get("/api/work-instructions/MMLE-50D/document").json()["document"]
    cover = _figure_pages(document)["page-work-instructions-cover"]
    artifact = store_draft_render_artifact(
        root, "MMLE-50D", document, cover["pageId"], _technical_capture(),
        source_revision=document["sourceRevision"], manual_plan_revision=document["manualPlanRevision"],
        api_route="work-instructions",
    )
    metadata = root / "mmle-50d" / "renders" / cover["figureRevision"] / f"{cover['pageId']}.json"
    for field in ("sourceRevision", "manualPlanRevision", "pageId", "figureRevision", "sha256"):
        metadata.write_text(json.dumps({**artifact, field: "wrong"}), encoding="ascii", newline="\n")
        before = _stored_bytes(root)
        attached = attach_draft_render_artifacts(root, "MMLE-50D", document)
        assert _figure_pages(attached)[cover["pageId"]]["renderRequest"]["image"]["status"] == "pending"
        assert _stored_bytes(root) == before
    before = _stored_bytes(root)
    with pytest.raises(OperationsManualArtifactError, match="unsupported work-instruction document schema"):
        store_draft_render_artifact(
            root, "MMLE-50D", {**document, "schemaVersion": 999}, cover["pageId"], _technical_capture(),
            source_revision=document["sourceRevision"], manual_plan_revision=document["manualPlanRevision"],
            api_route="work-instructions",
        )
    assert _stored_bytes(root) == before
