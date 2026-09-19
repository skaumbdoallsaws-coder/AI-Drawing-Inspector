"""Focused contracts for the evidence-backed operations-manual workspace."""

from __future__ import annotations

import copy
import hashlib
import io
import json
import struct
import zipfile
import zlib
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

import server
from ai_inspector.assembly_knowledge.library_registry import (
    load_documentation_library_sources,
)
from ai_inspector.documentation.registry import document_type_summaries
from ai_inspector.operations_manual.artifacts import (
    attach_draft_render_artifacts,
    store_draft_render_artifact,
)
from ai_inspector.operations_manual.document import (
    _evidence_citation_receipt,
    build_operations_manual_document,
    evaluate_release_gate,
)
from ai_inspector.operations_manual.flow import (
    FlowLayoutEngine,
    assert_no_orphan_continuation_pages,
    assert_pages_within_bounds,
)
from ai_inspector.operations_manual.exports import (
    OperationsManualExportError,
    _block_frame,
    _insert_htmlbox_checked,
    _safety_symbol_semantics,
    build_prototype_docx_bytes,
    build_prototype_pdf_bytes,
    prototype_export_readiness,
    store_prototype_docx,
    store_prototype_pdf,
)
from ai_inspector.operations_manual.nomenclature import (
    validate_publication_description,
)
from ai_inspector.parts_manual.catalog import build_occurrence_catalog
from ai_inspector.parts_manual.documentation import DocumentationSceneRepository


ROOT = Path(__file__).resolve().parents[1]
EVIDENCE_ROOT = ROOT / "docs" / "operations-manual"


def _mmle() -> tuple[dict, dict]:
    profile = load_documentation_library_sources(ROOT)["MMLE-50D"]["profile"]
    return profile, build_occurrence_catalog("MMLE-50D", profile)


def _document(*, scene: dict | None = None, scene_revision: str | None = None) -> dict:
    profile, catalog = _mmle()
    return build_operations_manual_document(
        profile,
        catalog,
        evidence_root=EVIDENCE_ROOT,
        documentation_scene=scene,
        documentation_scene_revision=scene_revision,
    )


def _png(width: int = 1200, height: int = 900) -> bytes:
    def chunk(kind: bytes, payload: bytes) -> bytes:
        body = kind + payload
        return struct.pack(">I", len(payload)) + body + struct.pack(">I", zlib.crc32(body))

    rows = b"".join(b"\x00" + (b"\xff\xff\xff\xff" * width) for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows, 9))
        + chunk(b"IEND", b"")
    )


def test_document_type_registry_exposes_one_shared_workspace() -> None:
    types = {row["documentType"]: row for row in document_type_summaries()}
    assert types["illustrated_parts_manual"]["workspace"] == "documentation"
    operations = types["operations_and_maintenance_manual"]
    assert operations["workspace"] == "documentation"
    assert operations["status"] == "review_available"
    assert operations["pageOrientation"] == "landscape"
    assert operations["supports"]["controlledPdf"] is False
    assert operations["supports"]["reviewPdf"] is True
    assert operations["supports"]["reviewDocx"] is True


def test_mmle_draft_is_evidence_bound_landscape_and_review_ready() -> None:
    document = _document()

    assert document["documentType"] == "operations_and_maintenance_manual"
    assert document["title"] == "MMLE-50D Electric Mobile Lift Operations and Maintenance Manual"
    assert document["revision"] is None
    assert document["pageCount"] >= 24
    assert document["publicationLayout"]["page"] == {
        "width": 960.0,
        "height": 540.0,
        "aspectRatio": 16 / 9,
        "orientation": "landscape",
        "logicalUnit": "pt",
    }
    cover_layout = document["publicationLayout"]["pageTypes"]["operations_cover"]
    assert cover_layout["coverStyleVersion"] == 2
    assert cover_layout["topAccent"] == {
        "x": 10, "y": 4, "width": 940, "height": 12,
    }
    assert cover_layout["bottomBand"] == {
        "x": 10, "y": 472, "width": 940, "height": 56,
    }
    assert cover_layout["illustration"]["y"] + cover_layout["illustration"]["height"] \
        < cover_layout["bottomBand"]["y"]
    assert document["releaseGate"]["status"] == "REVIEW_READY"
    assert document["releaseGate"]["controlledPdfAllowed"] is False
    assert document["releaseGate"]["reviewPdfAllowed"] is True
    assert document["releaseGate"]["reviewDocxAllowed"] is True
    assert document["releaseGate"]["controlledReleaseStatus"] == "PENDING_APPROVAL"
    assert document["releaseGate"]["findings"]
    assert document["safetySymbolPolicy"]["registerStatus"] == "empty_blocked"
    assert document["safetySymbolPolicy"]["draftRenderMode"] == "draft_geometric_fallback"
    assert document["safetySymbolPolicy"]["controlledPublicationAllowed"] is False
    evidence_summary = document["evidenceSummary"]
    assert evidence_summary["claimCount"] == 34
    assert evidence_summary["sourceCount"] == 27
    assert evidence_summary["citedClaimCount"] == 32
    assert evidence_summary["citedSourceCount"] == 5
    assert evidence_summary["approvedRegisteredClaimCount"] == 10
    assert evidence_summary["approvedCitedClaimCount"] == 9
    assert evidence_summary["reviewRequiredCitedClaimCount"] == 20
    assert evidence_summary["policyCitedClaimCount"] == 3
    assert evidence_summary["unusedRegisteredClaimCount"] == 2
    assert evidence_summary["conflictCount"] == 9
    assert evidence_summary["blockingConflictCount"] == 7
    assert evidence_summary["nonBlockingConflictCount"] == 2
    assert evidence_summary["blockingGapCount"] == 13
    assert evidence_summary["blockingEvidenceFindingCount"] == 20
    assert evidence_summary["governancePrerequisiteCount"] == 3
    assert [
        row["title"] for row in evidence_summary["reviewPrioritySections"]
    ] == ["10 Battery and Charging", "12 Inspection and Maintenance"]
    citations = document["evidenceCitations"]
    assert [row["citationNumber"] for row in citations] == [1, 2, 3, 4, 5]
    assert {row["sourceId"] for row in citations} == {
        "SRC-OEM-MMLE-WEB-2026",
        "SRC-OEM-MMLE-SERVICE-2012",
        "SRC-MHI-LIFT-GUIDE-2020",
        "SRC-CAD-MMLE-EXTRACT",
        "SRC-IP-MMLE-REGISTRY",
    }
    assert "SRC-REF-TLIFT440" not in {row["sourceId"] for row in citations}
    assert sum(bool(row["url"]) for row in citations) == 3
    assert all(row["claimCount"] > 0 and row["pageCount"] > 0 for row in citations)
    legacy_citation = next(
        row for row in citations
        if row["sourceId"] == "SRC-OEM-MMLE-SERVICE-2012"
    )
    assert legacy_citation["isPdf"] is True
    assert legacy_citation["sourcePageNumbers"] == [3, 4, 7, 8, 10, 11, 12, 13]
    assert legacy_citation["sourcePageCount"] == 8
    assert legacy_citation["sourcePageLocatorComplete"] is True
    assert legacy_citation["missingSourcePageClaimIds"] == []
    assert len(legacy_citation["claimSourcePageReferences"]) == (
        legacy_citation["claimCount"]
    )
    assert all(
        row["sourcePageNumbers"]
        for row in legacy_citation["claimSourcePageReferences"]
    )
    assert legacy_citation["manualPageNumbers"] == legacy_citation["pageNumbers"]
    assert legacy_citation["blockingConflictCount"] >= 2
    assert {
        "battery_and_charging_configuration",
        "parking_brake_configuration",
    }.issubset(set(legacy_citation["blockingConflictTopics"]))
    mhi_citation = next(
        row for row in citations
        if row["sourceId"] == "SRC-MHI-LIFT-GUIDE-2020"
    )
    assert mhi_citation["isPdf"] is True
    assert mhi_citation["sourcePageNumbers"] == [10]
    assert mhi_citation["sourcePageLocatorComplete"] is True
    current_web_citation = next(
        row for row in citations
        if row["sourceId"] == "SRC-OEM-MMLE-WEB-2026"
    )
    assert current_web_citation["isPdf"] is False
    assert current_web_citation["sourcePageNumbers"] == []
    assert current_web_citation["sourcePageLocatorComplete"] is None
    source_rows = [
        row
        for page in document["pages"]
        for block in page.get("layoutBlocks") or []
        if block.get("sourceBlockId") == "sources-table"
        for row in block["rows"]
    ]
    assert len(source_rows) == 5
    assert [row["cells"][0] for row in source_rows] == [
        row["title"] for row in citations
    ]
    assert all(page["pageCount"] == document["pageCount"] for page in document["pages"])
    assert_pages_within_bounds(
        page for page in document["pages"] if page["pageType"] == "operations_content"
    )

    figure_pages = [page for page in document["pages"] if page.get("renderRequest")]
    assert len(figure_pages) == 8
    assert {
        page["renderRequest"].get("figureId")
        for page in figure_pages
        if page["renderRequest"].get("figureId")
    } == {
        "OM-FIG-001", "OM-FIG-002", "OM-FIG-003", "OM-FIG-003B", "OM-FIG-004",
        "OM-FIG-005", "OM-FIG-006",
    }
    for page in figure_pages:
        request = page["renderRequest"]
        assert request["displayStyle"] == "hidden_lines_removed"
        assert request["image"]["background"] == "technical_white"
        width = request["image"]["minimumWidthPx"]
        height = request["image"]["minimumHeightPx"]
        target_ratio = request["image"]["targetAspectRatio"]
        assert 1200 <= width <= 4096
        assert 1200 <= height <= 3072
        assert max(width, height) >= 2400
        assert width * height >= 2400 * 1800
        assert width / height == pytest.approx(target_ratio, rel=0.001)
        assert request["occurrenceIds"]

    contents = document["pages"][2]
    assert any(
        block["blockType"] == "contents_list"
        for block in contents["layoutBlocks"]
    )
    assert not any(
        block["blockType"] in {"table", "contents_table"}
        for block in contents["layoutBlocks"]
    )
    safety_pages = [
        page for page in document["pages"] if page.get("sectionId") == "safety"
    ]
    safety_notes = [
        block
        for page in safety_pages
        for block in page.get("layoutBlocks") or []
        if block.get("blockType") == "note"
    ]
    assert {block.get("signalWord") for block in safety_notes} >= {
        "DANGER", "WARNING", "CAUTION", "NOTICE"
    }
    assert not any(
        block.get("sourceBlockId") in {"safety-signals", "safety-hazard-zones"}
        and block.get("blockType") == "table"
        for page in safety_pages
        for block in page.get("layoutBlocks") or []
    )

    overview = next(
        page for page in figure_pages
        if page["renderRequest"].get("figureId") == "OM-FIG-001"
    )
    assert overview["renderRequest"]["pose"] == "exploded"
    assert overview["renderRequest"]["showItemCallouts"] is True
    assert len(overview["renderRequest"]["calloutItems"]) == 10
    assert len(overview["manualGroupItems"]) == 10
    assert not any(
        "Evidence status" in str(block)
        for block in overview.get("layoutBlocks") or []
    )

    for figure_id in {
        "OM-FIG-002", "OM-FIG-003", "OM-FIG-003B", "OM-FIG-004", "OM-FIG-005", "OM-FIG-006"
    }:
        figure_page = next(
            page for page in figure_pages
            if page["renderRequest"].get("figureId") == figure_id
        )
        assert figure_page["renderRequest"]["showItemCallouts"] is True
        assert figure_page["renderRequest"]["calloutItems"]
        assert any(
            block.get("blockType") == "figure_legend"
            and block.get("items")
            for block in figure_page.get("layoutBlocks") or []
        )

    running_gear = next(
        page for page in figure_pages
        if page["renderRequest"].get("figureId") == "OM-FIG-006"
    )
    assert running_gear["renderRequest"]["pose"] == "exploded"
    assert len(running_gear["renderRequest"]["calloutItems"]) == 4
    assert all(
        row["anchorScope"] == "manual_group"
        for row in running_gear["renderRequest"]["calloutItems"]
    )
    assert len(running_gear["manualGroupItems"]) == 4

    scoped = {
        page["renderRequest"].get("figureId"): len(page["renderRequest"]["occurrenceIds"])
        for page in figure_pages
        if page["renderRequest"].get("figureId")
    }
    assert scoped["OM-FIG-002"] == 8
    assert scoped["OM-FIG-003"] == 29
    assert scoped["OM-FIG-003B"] == 16
    assert scoped["OM-FIG-004"] == 12
    assert scoped["OM-FIG-005"] == 18
    assert scoped["OM-FIG-006"] == 94


def test_pdf_evidence_receipt_never_invents_missing_source_pages() -> None:
    snapshot = {
        "sources": {
            "SRC-PDF": {
                "sourceId": "SRC-PDF",
                "title": "Synthetic Reference Manual",
                "authority": "OEM_LEGACY",
                "url": "https://example.invalid/reference.pdf",
            }
        },
        "claims": {
            "CLM-LOCATED": {
                "sourceIds": ["SRC-PDF"],
                "sourceLocations": [
                    {"sourceId": "SRC-PDF", "page": 4, "anchor": "Procedure"}
                ],
            },
            "CLM-MISSING": {
                "sourceIds": ["SRC-PDF"],
                "sourceLocations": [
                    {"sourceId": "SRC-PDF", "anchor": "Unpaginated excerpt"}
                ],
            },
        },
        "conflicts": [],
    }
    citations = _evidence_citation_receipt(
        snapshot,
        [
            {
                "pageNumber": 2,
                "evidenceClaimIds": ["CLM-LOCATED", "CLM-MISSING"],
            }
        ],
    )

    assert len(citations) == 1
    citation = citations[0]
    assert citation["manualPageNumbers"] == [2]
    assert citation["sourcePageNumbers"] == [4]
    assert citation["sourcePageLocatorComplete"] is False
    assert citation["missingSourcePageClaimIds"] == ["CLM-MISSING"]


def test_assembled_cover_ignores_component_presentation_overrides() -> None:
    baseline = _document()
    cover = next(
        page for page in baseline["pages"]
        if page["pageId"] == "page-operations-cover"
    )
    occurrence_id = cover["renderRequest"]["occurrenceIds"][0]
    scene = {
        "pages": {
            cover["pageId"]: {
                "figureOverride": {"cameraPreset": "front"},
                "occurrenceOverrides": {
                    occurrence_id: {"translation": [1.0, 2.0, 3.0]},
                },
                "manualGroupOverrides": {
                    "group-1": {"translation": [1.0, 0.0, 0.0]},
                },
                "pageElementOverrides": {
                    "illustration": {"translation": [0.05, 0.0, 0.0]},
                },
            },
        },
    }

    rebuilt = _document(scene=scene, scene_revision="scene-cover-override")
    rebuilt_cover = next(
        page for page in rebuilt["pages"]
        if page["pageId"] == "page-operations-cover"
    )
    composition = rebuilt_cover["renderRequest"]["composition"]

    assert composition["figureOverride"] == {"cameraPreset": "front"}
    assert composition["pageElementOverrides"]["illustration"] == {
        "translation": [0.05, 0.0, 0.0],
    }
    assert "occurrenceOverrides" not in composition
    assert "manualGroupOverrides" not in composition
    targets = server._operations_manual_editable_page_targets(rebuilt)
    assert targets[cover["pageId"]]["occurrence"] == []


def test_publication_nomenclature_and_component_coverage_are_validated() -> None:
    document = _document()
    requests = {
        page["renderRequest"].get("figureId"): page["renderRequest"]
        for page in document["pages"]
        if page.get("renderRequest")
    }
    for figure_id, request in requests.items():
        component_items = [
            row
            for row in request.get("calloutItems") or []
            if row.get("anchorScope") == "component_instance"
        ]
        if not component_items:
            continue
        coverage = request["calloutCoverage"]
        assert coverage["status"] == "PASS"
        assert coverage["scopeOccurrenceCount"] == len(request["occurrenceIds"])
        represented = []
        for item in component_items:
            validate_publication_description(item["description"])
            assert item["quantity"] == len(item["occurrenceIds"])
            represented.extend(item["occurrenceIds"])
        assert len(represented) == len(set(represented))
        assert set(represented) == set(request["occurrenceIds"]), figure_id

    battery_labels = {
        row["description"] for row in requests["OM-FIG-002"]["calloutItems"]
    }
    assert {
        "Battery Discharge Indicator",
        "Charger Plug",
        "Switch Handle",
        "Battery",
    } <= battery_labels
    shaft_labels = {
        row["description"] for row in requests["OM-FIG-003B"]["calloutItems"]
    }
    assert shaft_labels == {
        "Inner Scissor Pivot Tube",
        "Shaft, 228 mm",
        "Shaft Tube, 13 mm",
        "Shaft Tube, 10 mm",
        "Shaft Tube, 205 mm",
        "Shaft Tube, 55 mm",
        "Shaft, 25 x 160 mm",
        "Shaft Tube, 24.5 mm",
    }
    power_labels = {
        row["description"] for row in requests["OM-FIG-005"]["calloutItems"]
    }
    assert "Hydraulic Cartridge" in power_labels
    assert "Solenoid Valve Cartridge" in power_labels
    assert "Formed Hex Screw, M6 x 1.0 x 10" in power_labels


def test_customer_copy_has_no_orphan_or_generation_commentary() -> None:
    document = _document()
    content_pages = [
        page
        for page in document["pages"]
        if page.get("pageType") == "operations_content"
    ]
    assert_no_orphan_continuation_pages(content_pages)
    serialized = str(document).casefold()
    assert "intentionally not invented" not in serialized
    assert "values not supported by approved product documentation are not specified" not in serialized
    assert "metric conversions are intentionally omitted" not in serialized
    assert "legacy oem candidate" not in serialized
    assert "motor sound but platform does not rise" not in serialized
    assert "tlift440 operations manual" not in serialized
    published_component_copy = " ".join(
        str(item.get("description") or "")
        for page in document["pages"]
        for item in (page.get("renderRequest") or {}).get("calloutItems") or []
    ).casefold()
    assert "plain washer, 16 mm, regular" not in published_component_copy
    assert "plain washer, 16 mm" in published_component_copy


def test_keep_rules_preserve_semantic_blocks_across_page_breaks() -> None:
    document = _document()
    pages = document["pages"]

    for figure_id in {
        "OM-FIG-001", "OM-FIG-002", "OM-FIG-003", "OM-FIG-003B",
        "OM-FIG-004", "OM-FIG-005", "OM-FIG-006",
    }:
        page = next(
            row for row in pages
            if row.get("renderRequest", {}).get("figureId") == figure_id
        )
        expected_items = page["renderRequest"].get("calloutItems") or []
        legend = next(
            block for block in page.get("layoutBlocks") or []
            if block.get("blockType") == "figure_legend"
            and block.get("figureId") == figure_id
        )
        assert legend.get("continued") is False
        assert len(legend.get("items") or []) == len(expected_items)

    safety_page = next(
        page for page in pages
        if any(
            block.get("blockId") == "safety-general-title"
            for block in page.get("layoutBlocks") or []
        )
    )
    safety_ids = [block.get("blockId") for block in safety_page["layoutBlocks"]]
    assert "safety-no-rider" in safety_ids

    pre_use_page = next(page for page in pages if page.get("sectionId") == "pre-use")
    pre_use_list = next(
        block for block in pre_use_page["layoutBlocks"]
        if block.get("sourceBlockId") == "preuse-checklist"
    )
    assert len(pre_use_list["items"]) == 12
    assert any(
        block.get("blockId") == "preuse-fail"
        for block in pre_use_page["layoutBlocks"]
    )

    defect_blocks = [
        block
        for page in pages
        for block in page.get("layoutBlocks") or []
        if block.get("sourceBlockId") == "records-defect"
    ]
    assert len(defect_blocks) == 1
    assert len(defect_blocks[0]["rows"]) == 5


def test_safety_symbols_distinguish_hazards_from_notice() -> None:
    assert _safety_symbol_semantics("DANGER")["kind"] == "safety_alert"
    assert _safety_symbol_semantics("WARNING")["kind"] == "safety_alert"
    assert _safety_symbol_semantics("CAUTION")["kind"] == "safety_alert"
    assert _safety_symbol_semantics("NOTICE")["kind"] == "notice_information"
    assert len(
        {
            _safety_symbol_semantics(signal)["color"]
            for signal in ("DANGER", "WARNING", "CAUTION", "NOTICE")
        }
    ) == 4


def test_htmlbox_overflow_fails_instead_of_scaling_or_truncating() -> None:
    import fitz

    document = fitz.open()
    page = document.new_page()
    with pytest.raises(OperationsManualExportError, match="does not fit"):
        _insert_htmlbox_checked(
            page,
            fitz.Rect(10, 10, 90, 22),
            "<div>" + ("Safety-critical content " * 80) + "</div>",
            css="div { font-family: Arial; font-size: 10pt; line-height: 1.2; }",
            context="overflow fixture",
        )
    document.close()


def test_release_gate_is_computed_from_blocking_findings() -> None:
    ready = evaluate_release_gate([])
    assert ready["status"] == "READY"
    assert ready["controlledPdfAllowed"] is True
    assert ready["controlledDocxAllowed"] is True
    blocked = evaluate_release_gate(
        [{"findingId": "TEST-001", "blocking": True}]
    )
    assert blocked["status"] == "REVIEW_READY"
    assert blocked["blockingFindingCount"] == 1
    assert blocked["controlledReleasePrerequisiteCount"] == 1
    assert blocked["reviewPdfAllowed"] is True
    assert blocked["controlledPdfAllowed"] is False


def test_revision_addressed_export_is_reused_after_hash_validation(
    tmp_path: Path,
    monkeypatch,
) -> None:
    document = _document()
    payload = b"%PDF-1.7\nrevision-bound fixture\n%%EOF\n"
    monkeypatch.setattr(
        "ai_inspector.operations_manual.exports.build_prototype_pdf_bytes",
        lambda *_args, **_kwargs: payload,
    )
    first = store_prototype_pdf(tmp_path, "MMLE-50D", document)
    assert first["cacheHit"] is False
    monkeypatch.setattr(
        "ai_inspector.operations_manual.exports.build_prototype_pdf_bytes",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("cached export was rebuilt")
        ),
    )
    second = store_prototype_pdf(tmp_path, "MMLE-50D", document)
    assert second["cacheHit"] is True
    assert second["sha256"] == hashlib.sha256(payload).hexdigest()


def test_docx_renderer_version_invalidates_an_older_cached_export(
    tmp_path: Path,
    monkeypatch,
) -> None:
    document = _document()
    first_payload = b"PK\x03\x04old-theme"
    second_payload = b"PK\x03\x04branded-theme"
    monkeypatch.setattr(
        "ai_inspector.operations_manual.exports.build_prototype_docx_bytes",
        lambda *_args, **_kwargs: first_payload,
    )
    first = store_prototype_docx(tmp_path, "MMLE-50D", document)
    assert first["cacheHit"] is False
    assert first["rendererVersion"] == "operations-docx-theme-v3"

    metadata_path = (
        tmp_path
        / "mmle-50d"
        / "documents"
        / document["documentRevision"]
        / "review-docx.json"
    )
    metadata = json.loads(metadata_path.read_text(encoding="ascii"))
    metadata.pop("rendererVersion")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=True, sort_keys=True, indent=2) + "\n",
        encoding="ascii",
    )
    monkeypatch.setattr(
        "ai_inspector.operations_manual.exports.build_prototype_docx_bytes",
        lambda *_args, **_kwargs: second_payload,
    )
    second = store_prototype_docx(tmp_path, "MMLE-50D", document)
    assert second["cacheHit"] is False
    assert second["sha256"] == hashlib.sha256(second_payload).hexdigest()


def test_flow_engine_handles_a_synthetic_sixty_page_manual() -> None:
    sections = []
    for index in range(60):
        sections.append(
            {
                "sectionId": f"stress-{index + 1}",
                "title": f"Stress Section {index + 1}",
                "blocks": [
                    {
                        "blockId": f"stress-heading-{index + 1}",
                        "blockType": "heading",
                        "readingOrder": 1,
                        "payload": {"level": 1, "text": f"Stress Section {index + 1}"},
                        "evidenceClaimIds": [],
                    },
                    {
                        "blockId": f"stress-body-{index + 1}",
                        "blockType": "paragraph",
                        "readingOrder": 2,
                        "payload": {"text": " ".join(["Evidence-bound technical content"] * 120)},
                        "evidenceClaimIds": [],
                    },
                    {
                        "blockId": f"stress-table-{index + 1}",
                        "blockType": "table",
                        "readingOrder": 3,
                        "payload": {
                            "columns": ["Item", "Requirement", "Status"],
                            "rows": [
                                {"cells": [str(row + 1), "Deterministic row", "Draft"]}
                                for row in range(8)
                            ],
                        },
                        "evidenceClaimIds": [],
                    },
                ],
            }
        )

    pages = FlowLayoutEngine(start_page_number=1).layout(sections)
    assert len(pages) >= 60
    assert_pages_within_bounds(pages)
    assert all(page["layoutBlocks"] for page in pages)


def test_flow_engine_wraps_and_continues_long_table_rows_without_truncation() -> None:
    long_value = " ".join(["configuration-specific requirement"] * 260)
    sections = [{
        "sectionId": "long-table",
        "title": "Long Table",
        "blocks": [
            {
                "blockId": "long-table-heading",
                "blockType": "heading",
                "readingOrder": 1,
                "payload": {"level": 1, "text": "Long Table"},
                "evidenceClaimIds": [],
            },
            {
                "blockId": "long-table-data",
                "blockType": "table",
                "readingOrder": 2,
                "payload": {
                    "columns": ["Field", "Requirement"],
                    "rows": [{"cells": ["Operating boundary", long_value]}],
                },
                "evidenceClaimIds": [],
            },
        ],
    }]

    pages = FlowLayoutEngine(start_page_number=1).layout(sections)
    table_blocks = [
        block
        for page in pages
        for block in page["layoutBlocks"]
        if block["blockType"] == "table"
    ]
    reconstructed = " ".join(
        row["cells"][1]
        for block in table_blocks
        for row in block["rows"]
        if len(row.get("cells") or []) > 1
    )

    assert len(table_blocks) >= 2
    assert any(
        row.get("rowContinuation")
        for block in table_blocks
        for row in block["rows"]
    )
    assert reconstructed.split() == long_value.split()
    assert all(block["rowHeights"] for block in table_blocks)
    assert_pages_within_bounds(pages)


def test_scene_edits_are_revisioned_presentation_overrides(tmp_path: Path) -> None:
    profile, catalog = _mmle()
    baseline = build_operations_manual_document(profile, catalog, evidence_root=EVIDENCE_ROOT)
    page = next(row for row in baseline["pages"] if row["pageNumber"] == 4)
    block = next(row for row in page["layoutBlocks"] if row["blockType"] == "paragraph")
    repository = DocumentationSceneRepository(tmp_path / "scenes")
    loaded = repository.read(
        "MMLE-50D", catalog["sourceRevision"], baseline["manualPlanRevision"]
    )
    targets = server._operations_manual_editable_page_targets(baseline)
    changed = repository.apply_command(
        "MMLE-50D",
        catalog["sourceRevision"],
        baseline["manualPlanRevision"],
        base_revision=loaded["revision"],
        command={
            "operation": "update_text",
            "targetType": "page_element",
            "targetId": block["blockId"],
            "pageId": page["pageId"],
            "text": "Engineer-authored draft override.",
            "actor": "user",
        },
        page_targets=targets,
    )
    rebuilt = build_operations_manual_document(
        profile,
        catalog,
        evidence_root=EVIDENCE_ROOT,
        documentation_scene=changed["scene"],
        documentation_scene_revision=changed["revision"],
    )

    assert changed["revision"] != loaded["revision"]
    assert rebuilt["documentRevision"] != baseline["documentRevision"]
    composition = next(
        row for row in rebuilt["pages"] if row["pageId"] == page["pageId"]
    )["documentationComposition"]
    assert composition["pageElementOverrides"][block["blockId"]]["text"] == (
        "Engineer-authored draft override."
    )


def test_export_overrides_use_compiled_landscape_page_geometry() -> None:
    document = _document()
    page = next(
        row for row in document["pages"]
        if any(block.get("frame") for block in row.get("layoutBlocks") or [])
    )
    block = next(block for block in page["layoutBlocks"] if block.get("frame"))
    original = block["frame"]
    descriptor = copy.deepcopy(page)
    descriptor["documentationComposition"] = {
        "pageElementOverrides": {
            block["blockId"]: {
                "translation": [0.10, 0.20],
                "sizeDelta": [0.05, 0.10],
            }
        }
    }

    frame = _block_frame(descriptor, block, document)

    assert frame["x"] == pytest.approx(original["x"] + 96.0)
    assert frame["y"] == pytest.approx(original["y"] + 108.0)
    assert frame["width"] == pytest.approx(original["width"] + 48.0)
    assert frame["height"] == pytest.approx(original["height"] + 54.0)


def test_draft_capture_is_revision_bound_and_never_release_accepted(tmp_path: Path) -> None:
    document = _document()
    page = next(row for row in document["pages"] if row.get("renderRequest"))
    payload = _png()
    artifact = store_draft_render_artifact(
        tmp_path,
        "MMLE-50D",
        document,
        page["pageId"],
        payload,
        source_revision=document["sourceRevision"],
        manual_plan_revision=document["manualPlanRevision"],
    )
    attached = attach_draft_render_artifacts(tmp_path, "MMLE-50D", document)
    attached_page = next(row for row in attached["pages"] if row["pageId"] == page["pageId"])

    assert artifact["draftOnly"] is True
    assert artifact["acceptedForControlledPublication"] is False
    assert artifact["sha256"] == hashlib.sha256(payload).hexdigest()
    attached_image = attached_page["renderRequest"]["image"]
    assert all(attached_image[key] == value for key, value in artifact.items())
    assert attached_image["minimumForegroundOccupancy"] == 0.32
    assert attached_image["targetAspectRatio"] > 0

    stale = copy.deepcopy(document)
    stale["documentRevision"] = "a" * 64
    assert attach_draft_render_artifacts(tmp_path, "MMLE-50D", stale)["pages"][0][
        "renderRequest"
    ]["image"]["status"] == "pending"


def test_live_api_generates_and_exports_review_artifacts(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.setattr(server, "OPERATIONS_MANUAL_ROOT", tmp_path / "operations")
    client = TestClient(server.app)

    types = client.get("/api/documentation/types")
    assert types.status_code == 200
    assert any(
        row["documentType"] == "operations_and_maintenance_manual"
        for row in types.json()["documentTypes"]
    )
    generated = client.post("/api/operations-manual/MMLE-50D/generate")
    assert generated.status_code == 200
    body = generated.json()
    assert body["success"] is True
    assert body["document"]["pageCount"] >= 24
    assert body["document"]["releaseGate"]["status"] == "REVIEW_READY"
    assert body["document"]["evidenceSummary"]["citedSourceCount"] == 5
    assert len(body["document"]["evidenceCitations"]) == 5
    assert body["editableTargets"]["page-operations-cover"]["figure"]

    capture_required = client.post("/api/operations-manual/MMLE-50D/pdf")
    assert capture_required.status_code == 422
    assert capture_required.json()["error"] == "operations_manual_capture_required"

    document = body["document"]
    for page in document["pages"]:
        if not page.get("renderRequest"):
            continue
        store_draft_render_artifact(
            tmp_path / "operations",
            "MMLE-50D",
            document,
            page["pageId"],
            _png(),
            source_revision=document["sourceRevision"],
            manual_plan_revision=document["manualPlanRevision"],
        )
    exported = client.post("/api/operations-manual/MMLE-50D/pdf")
    assert exported.status_code == 200
    result = exported.json()
    assert result["stage"] == "review_exported"
    assert result["pdf"]["controlledRelease"] is False
    assert result["docx"]["controlledRelease"] is False
    assert result["pdf"]["pageCount"] == document["pageCount"]
    assert client.get(result["pdf"]["url"]).status_code == 200
    assert client.get(result["docx"]["url"]).status_code == 200


def test_generate_can_explicitly_rebaseline_an_obsolete_operations_scene(
    tmp_path: Path, monkeypatch
) -> None:
    profile, catalog = _mmle()
    del profile
    root = tmp_path / "operations"
    DocumentationSceneRepository(root).rebaseline(
        "MMLE-50D",
        catalog["sourceRevision"],
        "obsolete-six-page-plan",
    )
    monkeypatch.setattr(server, "OPERATIONS_MANUAL_ROOT", root)
    client = TestClient(server.app)

    context = client.get("/api/operations-manual/MMLE-50D")
    assert context.status_code == 200
    assert context.json()["sceneCurrent"] is False
    rejected = client.post("/api/operations-manual/MMLE-50D/generate")
    assert rejected.status_code == 409

    generated = client.post(
        "/api/operations-manual/MMLE-50D/generate?rebaseline=true"
    )
    assert generated.status_code == 200
    result = generated.json()
    assert result["rebaselined"] is True
    assert result["sourceCurrent"] is True
    assert result["manualPlanCurrent"] is True
    assert result["document"]["pageCount"] >= 24


def test_prototype_pdf_and_docx_share_one_revision(tmp_path: Path) -> None:
    document = _document()
    for page in document["pages"]:
        if page.get("renderRequest"):
            store_draft_render_artifact(
                tmp_path,
                "MMLE-50D",
                document,
                page["pageId"],
                _png(),
                source_revision=document["sourceRevision"],
                manual_plan_revision=document["manualPlanRevision"],
            )
    attached = attach_draft_render_artifacts(tmp_path, "MMLE-50D", document)
    assert prototype_export_readiness(attached)["status"] == "READY"
    pdf = build_prototype_pdf_bytes(tmp_path, "MMLE-50D", attached)
    docx = build_prototype_docx_bytes(tmp_path, "MMLE-50D", attached)
    assert pdf.startswith(b"%PDF")
    assert docx.startswith(b"PK")
    assert len(pdf) > 100_000
    assert len(docx) > 40_000
    import fitz

    rendered = fitz.open(stream=pdf, filetype="pdf")
    assert rendered[0].rect.width == pytest.approx(960.0)
    assert rendered[0].rect.height == pytest.approx(540.0)
    rendered_text = "\n".join(page.get_text() for page in rendered)
    assert len(rendered) == document["pageCount"]
    assert "Safety messages identify a hazard" in rendered_text
    assert all(
        signal_word in rendered_text
        for signal_word in ("DANGER", "WARNING", "CAUTION", "NOTICE")
    )
    assert "Pre-Use Inspection" in rendered_text
    assert "Troubleshooting" in rendered_text
    rendered.close()

    from docx import Document
    from docx.enum.section import WD_ORIENT

    editable = Document(io.BytesIO(docx))
    section = editable.sections[0]
    assert section.orientation == WD_ORIENT.LANDSCAPE
    assert section.page_width.inches == pytest.approx(960.0 / 72.0, abs=0.01)
    assert section.page_height.inches == pytest.approx(540.0 / 72.0, abs=0.01)
    assert section.different_first_page_header_footer is True
    assert "InspectorPro" in "".join(
        paragraph.text for paragraph in section.first_page_header.paragraphs
    )
    assert "OPERATIONS AND MAINTENANCE MANUAL" in "".join(
        paragraph.text for paragraph in section.header.paragraphs
    )
    assert str(document["documentNumber"]) in "".join(
        paragraph.text for paragraph in section.footer.paragraphs
    )
    assert str(document["product"]["name"]) in "".join(
        paragraph.text for paragraph in section.first_page_footer.paragraphs
    )

    with zipfile.ZipFile(io.BytesIO(docx)) as package:
        names = package.namelist()
        header_xml = b"".join(
            package.read(name)
            for name in names
            if name.startswith("word/header") and name.endswith(".xml")
        ).decode("utf-8")
        footer_xml = b"".join(
            package.read(name)
            for name in names
            if name.startswith("word/footer") and name.endswith(".xml")
        ).decode("utf-8")
        document_xml = package.read("word/document.xml").decode("utf-8")
    for shape_id in (
        "operations-cover-topAccent",
        "operations-cover-topRule",
        "operations-cover-leftAccent",
        "operations-cover-bottomBand",
        "operations-body-header-band",
        "operations-body-header-accent",
    ):
        assert shape_id in header_xml
    assert "operations-body-footer-rule" in footer_xml
    assert "#071B2A" in header_xml
    assert "#43B5EE" in header_xml
    assert "PAGE" in footer_xml
    assert "NUMPAGES" in footer_xml
    assert str(document["product"]["name"]) in document_xml


def test_sage_routes_only_explicit_operations_manual_draft_requests() -> None:
    route = server._safe_parts_manual_route(
        "Generate an operations and maintenance manual draft for this assembly."
    )
    plan, reason = server._compose_production_skill_prompt(route, mode="training")
    assert reason == ""
    assert plan is not None
    assert plan["selection"][0]["id"] == "publish-operations-manual"
    assert plan["allowed_tools"] == [
        "generate_operations_manual_draft",
        "publish_operations_manual",
    ]

    calls, warnings, added = server.ensure_operations_manual_draft_tool_call(
        [],
        "Generate an operations and maintenance manual draft for this assembly.",
        "inspector",
        None,
    )
    assert calls == [{"name": "generate_operations_manual_draft", "args": {}}]
    assert warnings == ["operations_manual_draft_backstop_added"]
    assert added is True
    assert server._required_parts_manual_workflow(
        "Generate an operations manual draft"
    ) == "documentation-publication"

    calls, warnings, added = server.ensure_operations_manual_draft_tool_call(
        [{"name": "generate_operations_manual_draft", "args": {}}],
        "What information belongs in an operations manual?",
        "inspector",
        None,
    )
    assert calls == []
    assert warnings == ["operations_manual_draft_dropped_without_explicit_request"]
    assert added is False

    publish_calls, publish_warnings, publish_added = (
        server.ensure_operations_manual_publication_tool_call(
            [],
            "Publish the operations and maintenance manual as PDF and DOCX.",
            "inspector",
            None,
        )
    )
    assert publish_calls == [{
        "name": "publish_operations_manual",
        "args": {"open_pdf": True, "open_docx": False},
    }]
    assert publish_warnings == ["operations_manual_publication_backstop_added"]
    assert publish_added is True
    assert server._safe_parts_manual_route(
        "What belongs in an operations manual?"
    )["speech_act"] == "analyze"


def test_explicit_documentation_chat_commands_bypass_the_model_and_keep_type() -> None:
    operations = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="operations manual for the active assembly",
            agent_type="deviation-analyst",
        )
    )
    assert operations is not None
    assert operations["tool_source"] == "deterministic_documentation"
    assert operations["tool_calls"] == [
        {"name": "generate_operations_manual_draft", "args": {}}
    ]

    parts = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="Build a parts manual for the active assembly.",
            agent_type="deviation-analyst",
        )
    )
    assert parts is not None
    assert parts["tool_calls"] == [
        {"name": "generate_parts_manual_draft", "args": {}}
    ]

    publish_current = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="Publish the manual.",
            agent_type="deviation-analyst",
            inspection_context={
                "attachments": {
                    "documentation": {
                        "document_type": "operations_and_maintenance_manual",
                    }
                }
            },
        )
    )
    assert publish_current is not None
    assert publish_current["tool_calls"][0]["name"] == (
        "publish_operations_manual"
    )

    informational = server._deterministic_documentation_chat_result(
        server.AgentChatRequest(
            message="What belongs in an operations manual?",
            agent_type="deviation-analyst",
        )
    )
    assert informational is None


def test_frontend_source_contract_exposes_operations_generation_hooks() -> None:
    source = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    assert "operations_and_maintenance_manual" in source
    assert "Generate Manual" in source
    assert "_documentationGenerateOperationsBaseline" in source
    assert "_documentationRevealPagesSequentially" in source
    assert "_documentationRevealPageProgressively" in source
    assert "documentationCoverChrome" in source
    assert "_documentationRenderCoverChrome" in source
    assert "documentation-cover-chrome-bottom-band" in source
    assert "_partsManualCaptureCurrentView(page, options = {})" in source
    assert "forceFigureCapture: options.forceFigureCapture !== false" in source
    assert "page_figure_capture_started" in source
    assert "page_figure_capture_stage" in source
    assert "documentation-figure-capture-progress" in source
    assert "documentation-figure-capture-takeover" in source
    assert "Operations Manual | Live CAD capture" in source
    assert "figure_capture_takeover_started" in source
    assert "figure_capture_takeover_finished" in source
    assert "generate_operations_manual_draft" in source
    assert "publish_operations_manual" in source
    assert "_documentationOperationsReceipt(documentModel, 'review_ready')" in source
    assert "'review_exported'" in source
    assert "reviewPdf: exported.pdf" in source
    assert "reviewDocx: exported.docx" in source
    assert "sourceCitations: (documentModel?.evidenceCitations || [])" in source
    assert "claimSourcePageReferences" in source
    assert "sourcePageNumbers" in source
    assert "source PDF page locator not recorded" in source
    assert "_documentationOperationsPageRangeLabel" in source
    assert "documentationFitPageStatus" in source
    assert "documentationFitWidthStatus" in source
    assert "documentationZoomPreset" in source
    assert "partsManualDocumentationZoomMode" in source
    assert "mode === 'fit_width'" in source
    assert "mode === 'fit_page'" in source
    assert "const resizeObserver = new ResizeObserver" in source
    assert "_operationsManualSemanticToolStatusLine" in source
    authority_formatter = source[
        source.index("function _documentationOperationsAuthorityLabel"):
        source.index("function _documentationOperationsReceipt")
    ]
    formatter = source[
        source.index("function _operationsManualAuthorityLabel"):
        source.index("function _facilityLayoutSemanticToolStatusLine")
    ]
    assert "Current manufacturer source" in authority_formatter
    assert "Legacy manufacturer manual" in authority_formatter
    assert "CAD model evidence" in authority_formatter
    assert "Your Operations Manual is ready for review in Documentation" in formatter
    assert "Your Operations Manual review PDF and editable Word document are ready" in formatter
    assert "controlled release remains blocked by ${controlledReleasePrerequisiteCount}" in formatter
    assert "**Deliverables**" in formatter
    assert "**What is established**" in formatter
    assert "**What needs your decision**" in formatter
    assert "**Claim-contributing sources**" in formatter
    assert "cited by ${claimCount} claim" in formatter
    assert "registered sources** contributed to" in formatter
    assert "Start with ${sectionLabels.join(' and ')}" in formatter
    assert "Build revision" in formatter
    operations_formatter = source[
        source.index("function _operationsManualSemanticToolStatusLine"):
        source.index("function _facilityLayoutSemanticToolStatusLine")
    ]
    assert "supports ${claimCount}" not in operations_formatter
    assert "unique evidence claims" not in operations_formatter
    assert "Capture validation:" not in operations_formatter
    assert "registeredLocation" not in formatter
    assert " - ${authority} - " not in formatter
    assert "documentation-page-operations" in source
    assert "pagePhase" in source
    assert "/api/operations-manual/${encodeURIComponent(assemblyNumber)}" in source
    assert "Export PDF" in source
    assert "Export DOCX" in source
    assert "| DRAFT" in source
    assert "PROTOTYPE - NOT FOR FIELD USE" not in source
    assert "CAD-grounded technical illustration" not in source
    assert "overflow-wrap: anywhere" in source
    assert "text-overflow: ellipsis" not in source[
        source.index(".documentation-operations-table"):
        source.index(".documentation-operations-block.cad_figure_caption")
    ]

    skill = (
        ROOT
        / "ai_inspector"
        / "agent_skills"
        / "publish-operations-manual"
        / "SKILL.md"
    ).read_text(encoding="utf-8")
    assert "## Inverted-pyramid reporting" in skill
    assert "one bold, self-contained conclusion" in skill
    assert "original source-document page" in skill
    assert "claimSourcePageReferences" in skill
