"""Live production proof for a customer-pilot parts-manual assembly.

The application owns generation, correction, validation, and publication. This
script only drives the public in-app workflow and verifies its receipts.
Generated evidence belongs under ``.runtime``; this proof remains source
controlled under ``tests``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import time

import fitz
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "assembly"


def run(
    *,
    base_url: str = "http://127.0.0.1:8125",
    assembly: str = "MMLE-50D",
    minimum_occurrences: int = 200,
    expected_pages: int = 15,
    expected_technical_pages: int = 12,
    output_dir: Path | None = None,
) -> int:
    output_dir = output_dir or ROOT / ".runtime" / "parts_manual_pilot_proof"
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "assembly": assembly,
        "baseUrl": base_url,
        "checks": {},
        "browserErrors": [],
        "consoleErrors": [],
    }

    def check(name: str, passed: bool, detail=None) -> None:
        report["checks"][name] = {"passed": bool(passed), "detail": detail}
        print(f"{'PASS' if passed else 'FAIL'} {name}", flush=True)

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--enable-gpu",
                    "--use-angle=d3d11",
                    "--disable-dev-shm-usage",
                    "--js-flags=--max-old-space-size=6144",
                ],
            )
            context = browser.new_context(viewport={"width": 1720, "height": 1080})
            page = context.new_page()
            page.set_default_timeout(1_200_000)
            page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))
            page.on(
                "console",
                lambda message: report["consoleErrors"].append(message.text)
                if message.type == "error"
                else None,
            )
            request = playwright.request.new_context(base_url=base_url, timeout=300_000)

            print(f"CHECKPOINT loading_{_slug(assembly)}", flush=True)
            page.goto(
                f"{base_url}/?assemblyProfile={assembly}",
                wait_until="domcontentloaded",
                timeout=300_000,
            )
            page.wait_for_function(
                """({ assembly, minimum }) => Boolean(
                    window.__compareDbg
                    && window.__compareDbg.state.partNumber === assembly
                    && window.__compareDbg.state.assyLiveScene
                    && window.__compareDbg.state.assyOccurrenceMeshMap
                    && Object.keys(window.__compareDbg.state.assyOccurrenceMeshMap).length >= minimum
                    && typeof window.__compareDbg.executeAgentTool === 'function'
                )""",
                arg={"assembly": assembly, "minimum": minimum_occurrences},
                timeout=600_000,
            )
            occurrence_count = page.evaluate(
                "() => Object.keys(window.__compareDbg.state.assyOccurrenceMeshMap).length"
            )
            page.screenshot(path=output_dir / "assembly-loaded.png", full_page=True)
            check(
                "component_aware_scene_loaded",
                occurrence_count >= minimum_occurrences,
                occurrence_count,
            )

            page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
            page.wait_for_function(
                """() => {
                    const value = window.__compareDbg.documentationGenerationSnapshot();
                    return value.workspaceOpen && value.blank && value.visiblePageCount === 0;
                }""",
                timeout=600_000,
            )
            blank = page.evaluate(
                "() => window.__compareDbg.documentationGenerationSnapshot()"
            )
            page.screenshot(path=output_dir / "documentation-blank.png", full_page=True)
            check(
                "documentation_starts_blank",
                blank.get("blank") is True and blank.get("visiblePageCount") == 0,
                blank,
            )

            page.evaluate(
                """() => {
                    window.__pilotPublication = { settled: false, result: null, error: null };
                    window.__compareDbg.executeAgentTool({
                        name: 'generate_and_publish_parts_manual',
                        args: {
                            approval_mode: 'approve_trusted_ready_candidates',
                            layout_mode: 'generate_baseline_if_missing',
                            open_pdf: false
                        }
                    }, 'deviation-analyst').then(
                        result => Object.assign(window.__pilotPublication, {
                            settled: true, result
                        }),
                        error => Object.assign(window.__pilotPublication, {
                            settled: true, error: String(error)
                        })
                    );
                }"""
            )
            last_signature = None
            deadline = time.monotonic() + 1_800
            while time.monotonic() < deadline:
                observation = page.evaluate(
                    """() => ({
                        ...window.__compareDbg.documentationGenerationSnapshot(),
                        settled: Boolean(window.__pilotPublication?.settled),
                        error: window.__pilotPublication?.error || null
                    })"""
                )
                signature = (
                    observation.get("generationState"),
                    observation.get("visiblePageCount"),
                    observation.get("workMessage"),
                    round(float(observation.get("progress") or 0), 3),
                    observation.get("settled"),
                )
                if signature != last_signature:
                    print("PROGRESS " + json.dumps(signature), flush=True)
                    last_signature = signature
                if observation.get("settled"):
                    break
                page.wait_for_timeout(750)
            else:
                raise TimeoutError("Pilot publication did not settle")

            result = page.evaluate("() => window.__pilotPublication.result")
            error = page.evaluate("() => window.__pilotPublication.error")
            memory_diagnostics = page.evaluate(
                "() => window.__compareDbg.state.partsManualCaptureMemoryDiagnostics || null"
            )
            report["toolResult"] = result
            report["toolError"] = error
            report["captureMemory"] = memory_diagnostics
            check(
                "live_app_reaches_published_stage",
                isinstance(result, dict)
                and result.get("ok") is True
                and result.get("stage") == "published",
                {"result": result, "error": error},
            )
            audit = (result or {}).get("manualPlanAudit") or {}
            check(
                "manual_plan_has_complete_coverage",
                audit.get("status") == "PASS"
                and audit.get("coveragePercent") == 100
                and audit.get("unassignedOccurrenceCount") == 0
                and audit.get("multiplyAssignedOccurrenceCount") == 0,
                audit,
            )

            document_response = request.get(
                f"/api/parts-manual/{assembly}/document", timeout=180_000
            )
            document_model = document_response.json()["document"]
            pages = document_model.get("pages") or []
            render_pages = [row for row in pages if row.get("renderRequest")]
            check(
                "document_has_expected_semantic_pages",
                len(pages) == expected_pages
                and len(render_pages) == expected_technical_pages,
                {
                    "pageCount": len(pages),
                    "technicalPageCount": len(render_pages),
                    "titles": [row.get("title") for row in pages],
                },
            )

            bom_rows = [
                bom
                for page_row in render_pages
                for bom in page_row.get("bom") or []
                if isinstance(bom, dict)
            ]
            check(
                "all_service_bom_rows_have_engineering_part_numbers",
                bool(bom_rows)
                and all(
                    row.get("partNumber")
                    and row.get("partNumber") != "Not specified"
                    for row in bom_rows
                ),
                {
                    "rowCount": len(bom_rows),
                    "missing": [
                        row for row in bom_rows
                        if row.get("partNumber") == "Not specified"
                    ][:10],
                },
            )

            quality_rows = []
            for descriptor in render_pages:
                image = descriptor["renderRequest"].get("image") or {}
                callout = (image.get("quality") or {}).get("calloutQuality") or {}
                quality_rows.append(
                    {
                        "pageId": descriptor.get("pageId"),
                        "figureNumber": descriptor.get("figureNumber"),
                        "status": image.get("status"),
                        "renderPipelineVersion": image.get("renderPipelineVersion"),
                        "leaderCrossings": callout.get("leaderCrossingCount", 0),
                        "geometryIntersections": callout.get(
                            "geometryIntersectionCount", 0
                        ),
                        "balloonCollisions": callout.get(
                            "leaderBalloonCollisionCount", 0
                        ),
                        "parallelCongestion": callout.get(
                            "nearParallelCongestionCount", 0
                        ),
                    }
                )
            check(
                "all_technical_captures_pass_callout_qa",
                len(quality_rows) == expected_technical_pages
                and all(
                    row["status"] == "ready"
                    and row["renderPipelineVersion"]
                    == document_model["renderPipelineVersion"]
                    and row["leaderCrossings"] == 0
                    and row["geometryIntersections"] == 0
                    and row["balloonCollisions"] == 0
                    and row["parallelCongestion"] == 0
                    for row in quality_rows
                ),
                quality_rows,
            )
            memory_samples = (memory_diagnostics or {}).get("samples") or []
            check(
                "sequential_capture_stays_within_browser_heap_budget",
                bool(memory_diagnostics)
                and len(memory_samples) >= expected_technical_pages + 2
                and int(memory_diagnostics.get("peakUsedJSHeapSize") or 0)
                <= int(memory_diagnostics.get("ceiling") or 0),
                memory_diagnostics,
            )

            pdf_descriptor = (result or {}).get("pdf") or {}
            if not pdf_descriptor.get("url"):
                raise RuntimeError("The workflow did not return a PDF artifact URL")
            pdf_response = request.get(pdf_descriptor["url"], timeout=180_000)
            pdf_bytes = pdf_response.body()
            pdf_path = output_dir / f"{_slug(assembly)}-illustrated-parts-manual.pdf"
            pdf_path.write_bytes(pdf_bytes)
            digest = hashlib.sha256(pdf_bytes).hexdigest()
            pdf = fitz.open(stream=pdf_bytes, filetype="pdf")
            check(
                "published_pdf_matches_receipt",
                pdf_response.ok
                and digest == pdf_descriptor.get("sha256")
                and len(pdf) == pdf_descriptor.get("pageCount") == expected_pages,
                {
                    "path": str(pdf_path),
                    "sha256": digest,
                    "bytes": len(pdf_bytes),
                    "pages": len(pdf),
                },
            )
            for page_number in range(1, len(pdf) + 1):
                if page_number <= 3 or page_number == len(pdf):
                    continue
                pixmap = pdf[page_number - 1].get_pixmap(
                    matrix=fitz.Matrix(1.4, 1.4), alpha=False
                )
                pixmap.save(output_dir / f"page-{page_number}.png")
            pdf.close()
            page.screenshot(
                path=output_dir / "documentation-published.png", full_page=True
            )

            check(
                "source_cad_geometry_is_unchanged",
                (result or {}).get("sourceCadChanged") is False,
                (result or {}).get("sourceCadChanged"),
            )
            check(
                "no_browser_runtime_errors",
                not report["browserErrors"],
                report["browserErrors"],
            )
            request.dispose()
            browser.close()
    except Exception as error:  # noqa: BLE001 - persist complete pilot diagnostics
        report["fatalError"] = f"{type(error).__name__}: {error}"
        print(report["fatalError"], flush=True)

    report_path = output_dir / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8"
    )
    return 0 if report.get("checks") and all(
        row.get("passed") for row in report["checks"].values()
    ) and not report.get("fatalError") else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify the live customer-pilot parts-manual workflow."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8125")
    parser.add_argument("--assembly", default="MMLE-50D")
    parser.add_argument("--minimum-occurrences", type=int, default=200)
    parser.add_argument("--expected-pages", type=int, default=15)
    parser.add_argument("--expected-technical-pages", type=int, default=12)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    return run(
        base_url=args.base_url.rstrip("/"),
        assembly=args.assembly,
        minimum_occurrences=args.minimum_occurrences,
        expected_pages=args.expected_pages,
        expected_technical_pages=args.expected_technical_pages,
        output_dir=args.output_dir,
    )


if __name__ == "__main__":
    raise SystemExit(main())
