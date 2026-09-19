"""Run the live Specification Sheet workflow and retain visual/export evidence."""

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
        default=".runtime/specification_sheet_proof",
        type=Path,
    )
    args = parser.parse_args()
    output = args.out.resolve()
    output.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "url": args.url,
        "pageErrors": [],
        "httpFailures": [],
        "checks": {},
    }

    def record(name: str, ok: bool, detail: object = None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        if not ok:
            raise RuntimeError(f"specification-sheet verification failed: {name}: {detail}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
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
            "product_specification_sheet"
        )
        page.wait_for_function(
            """() => Boolean(
                document.querySelector('#documentationWorkspace.workflow-mode')
                && document.querySelector('#documentationTypeRibbonSelect')?.value
                    === 'product_specification_sheet'
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
                window.__specificationGenerationSettled = false;
                window.__specificationGenerationOutcome = null;
                window.__specificationGenerationPromise =
                    window.__compareDbg.executeAgentTool(
                        {name: 'generate_specification_sheet_draft', args: {}},
                        'inspector'
                    ).then(result => {
                        window.__specificationGenerationOutcome = {
                            status: 'resolved', result,
                        };
                        return result;
                    }).catch(error => {
                        window.__specificationGenerationOutcome = {
                            status: 'rejected',
                            error: String(error?.stack || error?.message || error),
                        };
                        throw error;
                    }).finally(() => {
                        window.__specificationGenerationSettled = true;
                    });
            }"""
        )
        capture_takeover_seen = False
        generation_samples: list[dict[str, object]] = []
        deadline = time.monotonic() + 600
        last_log = 0.0
        while time.monotonic() < deadline:
            sample = page.evaluate(
                "window.__compareDbg.documentationGenerationSnapshot()"
            )
            generation_samples.append(sample)
            capture_takeover_seen = capture_takeover_seen or page.locator(
                ".documentation-figure-capture-takeover"
            ).count() > 0
            settled = page.evaluate(
                "Boolean(window.__specificationGenerationSettled)"
            )
            if time.monotonic() - last_log >= 2:
                last_log = time.monotonic()
                print(
                    "generation",
                    json.dumps(
                        {
                            "state": sample["generationState"],
                            "working": sample["working"],
                            "message": sample["workMessage"],
                            "visible": sample["visiblePageCount"],
                            "events": len(sample.get("events") or []),
                            "settled": settled,
                        },
                        ensure_ascii=True,
                    ),
                    flush=True,
                )
            if settled:
                break
            if sample["generationState"] in {"failed", "cancelled"}:
                raise RuntimeError(
                    "specification-sheet generation entered terminal failure: "
                    + json.dumps(sample, ensure_ascii=True)
                )
            page.wait_for_timeout(80)
        else:
            raise RuntimeError("specification-sheet generation did not complete")
        generation = page.evaluate(
            "async () => window.__specificationGenerationPromise"
        )
        report["generation"] = generation
        report["captureTakeoverSeen"] = capture_takeover_seen
        record(
            "generation_reached_review_ready",
            generation.get("ok") is True
            and generation.get("stage") == "review_ready",
            generation,
        )
        record("live_capture_takeover_visible", capture_takeover_seen)

        state = page.evaluate(
            """() => {
                const documentModel = window.__compareDbg.state.partsManualDocumentation?.document;
                const pageModel = documentModel?.pages?.[0];
                const surface = document.querySelector('#documentationPublicationSurface');
                const bounds = surface?.getBoundingClientRect();
                return {
                    documentType: documentModel?.documentType,
                    pageCount: documentModel?.pageCount,
                    pageSize: documentModel?.publicationLayout?.page,
                    renderRequest: pageModel?.renderRequest,
                    surface: bounds ? {
                        width: bounds.width,
                        height: bounds.height,
                        aspectRatio: bounds.width / bounds.height,
                    } : null,
                    railCount: document.querySelectorAll(
                        '#documentationPageList .documentation-page-item'
                    ).length,
                    inspectorOpen: document.querySelector(
                        '#documentationWorkspace.inspector-open'
                    ) !== null,
                };
            }"""
        )
        report["workspace"] = state
        record(
            "portrait_page_contract",
            state["documentType"] == "product_specification_sheet"
            and state["pageCount"] == 1
            and state["pageSize"]["orientation"] == "portrait"
            and abs(float(state["surface"]["aspectRatio"]) - (612 / 792)) < 0.01,
            state,
        )
        record("single_thumbnail", state["railCount"] == 1, state["railCount"])
        request = state["renderRequest"]
        image = request.get("image") or {}
        record(
            "fresh_neutral_shaded_capture",
            request.get("pose") == "assembled"
            and request.get("illustrationStyle") == "SHADED_COLOR"
            and request.get("showItemCallouts") is False
            and request.get("calloutItems") == []
            and image.get("status") == "ready"
            and image.get("documentRevision")
                == generation.get("documentRevision"),
            request,
        )
        record("inspector_closed_by_default", state["inspectorOpen"] is False)
        page.screenshot(path=output / "workspace.png", full_page=True)
        page.locator("#documentationPublicationSurface").screenshot(
            path=output / "sheet_viewport.png"
        )

        publication = page.evaluate(
            """async () => window.__compareDbg.executeAgentTool(
                {name: 'publish_specification_sheet', args: {open_pdf: false}},
                'inspector'
            )"""
        )
        report["publication"] = publication
        record(
            "publication_reached_review_exported",
            publication.get("ok") is True
            and publication.get("stage") == "review_exported"
            and publication.get("freshCaptureRun") is True,
            publication,
        )
        pdf_info = publication.get("reviewPdf") or {}
        record(
            "review_pdf_receipt",
            pdf_info.get("status") == "ready"
            and pdf_info.get("pageCount") == 1
            and pdf_info.get("controlledRelease") is False,
            pdf_info,
        )
        base = args.url.split("/?", 1)[0].rstrip("/")
        pdf_path = output / "MMLE-50D-specification-sheet.pdf"
        pdf_payload = _download(base + str(pdf_info["url"]), pdf_path)
        record(
            "pdf_hash_matches_receipt",
            hashlib.sha256(pdf_payload).hexdigest() == pdf_info.get("sha256"),
        )
        pdf = fitz.open(stream=pdf_payload, filetype="pdf")
        try:
            record("pdf_is_one_page", pdf.page_count == 1, pdf.page_count)
            pdf_page = pdf[0]
            page_rect = pdf_page.rect
            record(
                "pdf_is_letter_portrait",
                abs(page_rect.width - 612) < 0.1
                and abs(page_rect.height - 792) < 0.1,
                [page_rect.width, page_rect.height],
            )
            text = pdf_page.get_text()
            record(
                "pdf_has_expected_content",
                all(
                    value in text
                    for value in (
                        "MMLE-50D Electric Mobile Lift",
                        "Specifications",
                        "1,100 lb",
                        "REVIEW",
                    )
                ),
            )
            pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(1.6, 1.6), alpha=False)
            pixmap.save(output / "sheet_pdf.png")
        finally:
            pdf.close()

        record("no_page_errors", not report["pageErrors"], report["pageErrors"])
        record("no_http_failures", not report["httpFailures"], report["httpFailures"])
        browser.close()

    report_path = output / "full_report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=True, indent=2, sort_keys=True),
        encoding="ascii",
    )
    print(json.dumps({
        "status": "PASS",
        "checks": len(report["checks"]),
        "pdf": str((output / "MMLE-50D-specification-sheet.pdf").resolve()),
        "report": str(report_path.resolve()),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
