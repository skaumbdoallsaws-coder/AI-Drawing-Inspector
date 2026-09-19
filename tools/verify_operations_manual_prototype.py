"""Run the live Operations Manual workflow and retain visual/export evidence."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import time
import urllib.request

import fitz
from playwright.sync_api import sync_playwright


DEFAULT_URL = "http://127.0.0.1:8125/?assemblyProfile=MMLE-50D"
SCREENSHOT_PAGES = {
    "page-operations-cover": "01_cover",
    "page-safety-1": "05_safety",
    "page-product-overview-1": "07_product_overview",
    "page-controls-1": "09_controls",
    "page-operation-1": "13_operating_instructions",
    "page-maintenance-1": "19_maintenance",
    "page-technical-reference-1": "20_lift_scissor_and_pivots",
    "page-technical-reference-2": "21_lift_shafts_and_tubes",
    "page-technical-reference-3": "22_hydraulic_cylinder",
    "page-technical-reference-4": "23_hydraulic_power_pack",
}


def _download(url: str, destination: Path) -> bytes:
    with urllib.request.urlopen(url, timeout=120) as response:
        payload = response.read()
    destination.write_bytes(payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument(
        "--out",
        default=".runtime/operations_manual_proof",
        type=Path,
    )
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "url": args.url,
        "pageErrors": [],
        "httpFailures": [],
        "captures": [],
        "checks": {},
    }

    def record(name: str, ok: bool, detail: object = None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            raise RuntimeError(f"operations-manual verification failed: {name}: {detail}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--js-flags=--expose-gc"],
        )
        page = browser.new_page(
            viewport={"width": 1720, "height": 1080},
            device_scale_factor=1,
        )
        page.set_default_timeout(180_000)
        page.on("pageerror", lambda error: report["pageErrors"].append(str(error)))

        def record_response(response) -> None:
            if response.status < 400:
                return
            if any(
                token in response.url
                for token in ("/api/drawing-map/", "/api/drawing-pdf/", "/api/part-features/")
            ):
                return
            report["httpFailures"].append(
                {"status": response.status, "url": response.url}
            )

        page.on("response", record_response)
        page.goto(args.url, wait_until="domcontentloaded", timeout=180_000)
        page.wait_for_function(
            """() => Boolean(
                window.__compareDbg?.state?.assyLiveScene
                && window.__compareDbg?.state?.assyOccurrenceMeshMap
                && window.__compareDbg?.executeAgentTool
            )""",
            timeout=180_000,
        )
        page.get_by_role("button", name="Parts Manual", exact=True).click()
        page.locator("#documentationWorkspace").wait_for(
            state="visible", timeout=120_000
        )
        page.locator("#documentationTypeRibbonSelect").select_option(
            "operations_and_maintenance_manual"
        )
        page.wait_for_function(
            """() => Boolean(
                document.querySelector('#documentationWorkspace.workflow-mode')
                && document.querySelector('#documentationTypeRibbonSelect')?.value
                    === 'operations_and_maintenance_manual'
                && !document.querySelector('#documentationWorkspace.busy')
            )""",
            timeout=120_000,
        )
        blank = page.evaluate(
            """() => ({
                snapshot: window.__compareDbg.documentationGenerationSnapshot(),
                railPageCount: document.querySelectorAll(
                    '#documentationPageList .documentation-page-item'
                ).length,
            })"""
        )
        report["blankEntry"] = blank
        record(
            "blank_first_entry",
            bool(blank["snapshot"]["blank"])
            and blank["snapshot"]["visiblePageCount"] == 0
            and blank["railPageCount"] == 0,
            blank,
        )
        page.evaluate(
            """() => {
                window.__operationsGenerationPromise =
                    window.__compareDbg.executeAgentTool(
                        {name: 'generate_operations_manual_draft', args: {}},
                        'inspector'
                    );
            }"""
        )
        page.wait_for_function(
            """() => window.__compareDbg.documentationGenerationSnapshot()
                .generationState === 'running'""",
            timeout=120_000,
        )
        generation_samples: list[dict[str, object]] = []
        deadline = time.monotonic() + 1200
        while time.monotonic() < deadline:
            sample = page.evaluate(
                "window.__compareDbg.documentationGenerationSnapshot()"
            )
            generation_samples.append(sample)
            if sample["generationState"] == "complete" and not sample["working"]:
                break
            page.wait_for_timeout(100)
        else:
            raise RuntimeError("operations-manual generation did not complete")
        generation = page.evaluate(
            "async () => window.__operationsGenerationPromise"
        )
        report["generation"] = generation
        visible_counts = [int(row["visiblePageCount"]) for row in generation_samples]
        report["generationSamples"] = [
            {
                "generationState": row["generationState"],
                "visiblePageCount": row["visiblePageCount"],
                "totalPageCount": row["totalPageCount"],
                "nextPageId": row["nextPageId"],
            }
            for row in generation_samples
        ]
        record(
            "pages_reveal_monotonically",
            bool(visible_counts)
            and visible_counts == sorted(visible_counts)
            and visible_counts[-1] >= 24
            and len(set(visible_counts)) >= 4,
            visible_counts,
        )
        completed_snapshot = generation_samples[-1]
        phase_events = [
            row
            for row in completed_snapshot["events"]
            if row.get("type") == "page_phase"
        ]
        phases_by_page: dict[str, list[str]] = {}
        for event in phase_events:
            page_id = str(event.get("pageId") or "")
            phase = str(event.get("phase") or "")
            phases = phases_by_page.setdefault(page_id, [])
            if not phases or phases[-1] != phase:
                phases.append(phase)
        expected_phases = [
            "shell", "title", "illustration", "tableHeader",
            "rows", "annotations", "settled",
        ]
        ordered_phase_pages = [
            page_id
            for page_id, phases in phases_by_page.items()
            if phases == expected_phases
        ]
        report["phaseSequences"] = phases_by_page
        record(
            "progressive_phase_order",
            bool(ordered_phase_pages) and not completed_snapshot["pagePhase"],
            {
                "matchingPageIds": ordered_phase_pages,
                "pagePhase": completed_snapshot["pagePhase"],
            },
        )
        retained_events = completed_snapshot["events"]
        capture_start_events = [
            row for row in retained_events
            if row.get("type") == "page_figure_capture_started"
        ]
        capture_stage_events = [
            row for row in retained_events
            if row.get("type") == "page_figure_capture_stage"
        ]
        capture_events = [
            row for row in retained_events
            if row.get("type") == "page_figure_captured"
        ]
        settled_at = {
            str(row.get("pageId") or ""): int(row.get("at") or 0)
            for row in retained_events
            if row.get("type") == "page_phase" and row.get("phase") == "settled"
        }
        render_readiness = page.evaluate(
            """() => {
                const pages = window.__compareDbg.state.partsManualDocumentation
                    ?.document?.pages || [];
                const required = pages.filter(row => row.renderRequest);
                return {
                    requiredPageIds: required.map(row => row.pageId),
                    pendingPageIds: required.filter(
                        row => row.renderRequest?.image?.status !== 'ready'
                    ).map(row => row.pageId),
                };
            }"""
        )
        record(
            "technical_capture_runs_during_page_build",
            len(capture_start_events) == len(render_readiness["requiredPageIds"]) == 9
            and len(capture_events) == 9
            and not render_readiness["pendingPageIds"]
            and all(bool(row.get("forceFresh")) for row in capture_start_events)
            and all(
                int(row.get("at") or 0)
                <= settled_at.get(str(row.get("pageId") or ""), 0)
                for row in capture_events
            )
            and {
                "publicationRender", "calloutRouting", "accepted"
            } <= {str(row.get("stage") or "") for row in capture_stage_events},
            {
                "captureStartEvents": capture_start_events,
                "captureStageEvents": capture_stage_events,
                "captureEvents": capture_events,
                "renderReadiness": render_readiness,
            },
        )
        phase_count_before_revisit = len(phase_events)
        revisit_page_id = ordered_phase_pages[-1]
        page.evaluate(
            "async pageId => window._documentationActivatePage(pageId)",
            revisit_page_id,
        )
        page.wait_for_timeout(250)
        phase_count_after_revisit = page.evaluate(
            """() => (window.__compareDbg.documentationGenerationSnapshot().events || [])
                .filter(row => row.type === 'page_phase').length"""
        )
        record(
            "settled_page_revisit_does_not_replay",
            phase_count_after_revisit == phase_count_before_revisit,
            {
                "before": phase_count_before_revisit,
                "after": phase_count_after_revisit,
                "pageId": revisit_page_id,
            },
        )
        snapshot = page.evaluate(
            """() => {
                const payload = window.__compareDbg.state.partsManualDocumentation;
                const pages = payload?.document?.pages || [];
                return {
                    documentRevision: payload?.document?.documentRevision,
                    pageCount: pages.length,
                    renderPageIds: pages.filter(row => row.renderRequest).map(row => row.pageId),
                    pendingRenderPageIds: pages.filter(
                        row => row.renderRequest && row.renderRequest.image?.status !== 'ready'
                    ).map(row => row.pageId),
                    titles: pages.map(row => row.title),
                    releaseGate: payload?.document?.releaseGate,
                    evidenceSummary: payload?.document?.evidenceSummary,
                    evidenceCitations: payload?.document?.evidenceCitations,
                    pages: pages.map(row => ({
                        pageId: row.pageId,
                        pageNumber: row.pageNumber,
                        title: row.title,
                    })),
                };
            }"""
        )
        report["document"] = snapshot
        if snapshot["pageCount"] < 24 or len(snapshot["renderPageIds"]) < 9:
            raise RuntimeError(
                "expanded operations manual is incomplete: "
                f"generation={generation}; document={snapshot}"
            )
        record(
            "five_used_sources_are_revision_bound_and_reported",
            snapshot["evidenceSummary"]["citedSourceCount"] == 5
            and generation.get("citedSourceCount") == 5
            and len(generation.get("sourceCitations") or []) == 5
            and {
                row.get("sourceId") for row in generation.get("sourceCitations") or []
            } == {
                "SRC-OEM-MMLE-WEB-2026",
                "SRC-OEM-MMLE-SERVICE-2012",
                "SRC-MHI-LIFT-GUIDE-2020",
                "SRC-CAD-MMLE-EXTRACT",
                "SRC-IP-MMLE-REGISTRY",
            }
            and len(generation.get("chatCitationLines") or []) == 5,
            {
                "evidenceSummary": snapshot["evidenceSummary"],
                "sourceCitations": generation.get("sourceCitations"),
                "chatCitationLines": generation.get("chatCitationLines"),
            },
        )

        for page_id, stem in SCREENSHOT_PAGES.items():
            page.evaluate(
                """async pageId => {
                    await window._documentationActivatePage(pageId);
                    window._documentationForceSettledRender?.(
                        window.__compareDbg.state.partsManualDocumentation.document.pages
                            .find(row => row.pageId === pageId)
                    );
                }""",
                page_id,
            )
            page.wait_for_timeout(250)
            page.screenshot(path=output / f"workspace_{stem}.png", full_page=True)

        for index, page_id in enumerate(snapshot["pendingRenderPageIds"], start=1):
            artifact = page.evaluate(
                """async pageId => {
                    const payload = window.__compareDbg.state.partsManualDocumentation;
                    const target = payload.document.pages.find(row => row.pageId === pageId);
                    const artifacts = await window._documentationCaptureAllPages({
                        documentModel: payload.document,
                        pages: [target],
                        nested: false,
                        throwOnError: true,
                        suppressSuccess: true,
                    });
                    return artifacts[0];
                }""",
                page_id,
            )
            report["captures"].append(
                {"index": index, "pageId": page_id, "artifact": artifact}
            )
            page.evaluate("() => window.gc?.()")
            page.wait_for_timeout(120)

        if generation.get("stage") == "review_exported":
            exported = {
                "success": True,
                "stage": generation["stage"],
                "documentRevision": generation["documentRevision"],
                "releaseGate": {
                    "status": generation["releaseGateStatus"],
                    "controlledPdfAllowed": False,
                },
                "pdf": generation["reviewPdf"],
                "docx": generation["reviewDocx"],
                "source": "sage_tool_receipt",
            }
        else:
            raise RuntimeError(
                "Sage did not complete the end-to-end manual export: "
                f"{generation}"
            )
        report["export"] = exported

        page.emulate_media(reduced_motion="reduce")
        reduced = page.evaluate(
            """async () => {
                const payload = window.__compareDbg.state.partsManualDocumentation;
                window.__compareDbg.state.partsManualDocumentationGenerationEvents = [];
                const work = _documentationBeginSageWork('Reduced-motion operations proof');
                _documentationPreparePageGeneration(payload, { revealAll: false });
                try {
                    await _documentationRevealPagesSequentially(payload, {
                        work,
                        prepared: true,
                    });
                    _documentationEndSageWork(work, 'complete', 'Reduced-motion proof complete.');
                } catch (error) {
                    _documentationEndSageWork(work, 'failed', error.message);
                    throw error;
                }
                return window.__compareDbg.documentationGenerationSnapshot();
            }"""
        )
        page.emulate_media(reduced_motion="no-preference")
        report["reducedMotion"] = reduced
        record(
            "reduced_motion_skips_visual_phases",
            reduced["generationState"] == "complete"
            and reduced["visiblePageCount"] == reduced["totalPageCount"]
            and not reduced["pagePhase"]
            and not [
                row for row in reduced["events"]
                if row.get("type") == "page_phase"
            ],
            reduced,
        )
        browser.close()

    base_url = args.url.split("?", 1)[0].rstrip("/")
    pdf_url = base_url + str(exported["pdf"]["url"])
    docx_url = base_url + str(exported["docx"]["url"])
    pdf_path = output / "MMLE-50D-operations-manual.pdf"
    docx_path = output / "MMLE-50D-operations-manual.docx"
    pdf_payload = _download(pdf_url, pdf_path)
    docx_payload = _download(docx_url, docx_path)
    pdf = fitz.open(stream=pdf_payload, filetype="pdf")
    extracted_words = sum(len(page.get_text("words")) for page in pdf)
    page_number_by_id = {
        str(row["pageId"]): int(row["pageNumber"])
        for row in snapshot["pages"]
    }
    raster_pages = sorted({
        0,
        2,
        *[
            page_number_by_id[page_id] - 1
            for page_id in SCREENSHOT_PAGES
            if page_id in page_number_by_id
        ],
    })
    for page_index in raster_pages:
        if page_index >= len(pdf):
            continue
        pixmap = pdf[page_index].get_pixmap(matrix=fitz.Matrix(1.35, 1.35), alpha=False)
        pixmap.save(output / f"pdf_page_{page_index + 1:02d}.png")
    report["artifacts"] = {
        "pdf": {
            "path": str(pdf_path),
            "bytes": len(pdf_payload),
            "sha256": hashlib.sha256(pdf_payload).hexdigest(),
            "pages": len(pdf),
            "words": extracted_words,
        },
        "docx": {
            "path": str(docx_path),
            "bytes": len(docx_payload),
            "sha256": hashlib.sha256(docx_payload).hexdigest(),
            "signature": docx_payload[:4].hex(),
        },
    }
    pdf.close()
    (output / "full_report.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=True),
        encoding="utf-8",
    )
    print(json.dumps(report["artifacts"], indent=2))
    if report["pageErrors"] or report["httpFailures"]:
        print(json.dumps({
            "pageErrors": report["pageErrors"],
            "httpFailures": report["httpFailures"],
        }, indent=2))
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
