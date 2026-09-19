"""Browser proof for Sage's end-to-end illustrated-parts-manual tool."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sys
import time

import fitz

from parts_manual_smoke_support import (
    IsolatedPartsManualServer,
    seed_internal_legacy_section,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime" / "parts_manual_sage_publication_proof"
OUT.mkdir(parents=True, exist_ok=True)
ASSEMBLY = "tricycle"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {
        "assembly": ASSEMBLY,
        "checks": {},
        "browserErrors": [],
        "toolResult": None,
    }

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        print(f"{'PASS' if ok else 'FAIL'} {name}")

    server = IsolatedPartsManualServer(ROOT, OUT, ASSEMBLY)
    try:
        server.start()
        report["appUrl"] = server.app_url
        with sync_playwright() as playwright:
            launch_args = (
                ["--enable-gpu", "--use-angle=d3d11"]
                if sys.platform == "win32"
                else []
            )
            browser = playwright.chromium.launch(headless=True, args=launch_args)
            context = browser.new_context(viewport={"width": 1720, "height": 1080})
            page = context.new_page()
            page.set_default_timeout(600_000)
            request = playwright.request.new_context(
                base_url=server.app_url,
                timeout=300_000,
            )
            page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))

            initial = seed_internal_legacy_section(request, server.app_url, ASSEMBLY)
            initial_source_revision = initial["sourceRevision"]
            record(
                "legacy_plan_requires_replacement",
                initial["publicationReadiness"]["status"] == "FAIL",
                initial["publicationReadiness"],
            )

            page.goto(
                f"{server.app_url}/?assemblyProfile={ASSEMBLY}",
                wait_until="domcontentloaded",
                timeout=300_000,
            )
            page.wait_for_function(
                """assembly => Boolean(
                    window.__compareDbg
                    && window.__compareDbg.state.partNumber === assembly
                    && window.__compareDbg.state.assyLiveScene
                    && window.__compareDbg.state.assyOccurrenceMeshMap
                )""",
                arg=ASSEMBLY,
                timeout=300_000,
            )

            page.wait_for_function(
                "() => typeof window.__compareDbg?.executeAgentTool === 'function'",
                timeout=90_000,
            )
            page.evaluate("() => window.__compareDbg.openDocumentationWorkflow()")
            page.wait_for_function(
                """() => {
                    const value = window.__compareDbg.documentationGenerationSnapshot();
                    return value.workspaceOpen && value.blank
                        && value.visiblePageCount === 0;
                }""",
                timeout=300_000,
            )
            blank_snapshot = page.evaluate(
                "() => window.__compareDbg.documentationGenerationSnapshot()"
            )
            record(
                "documentation_workflow_starts_blank",
                blank_snapshot.get("workspaceOpen") is True
                and blank_snapshot.get("blank") is True
                and blank_snapshot.get("visiblePageCount") == 0,
                blank_snapshot,
            )
            page.screenshot(
                path=str(OUT / "documentation_blank_before_sage.png"),
                full_page=True,
            )

            page.evaluate(
                """() => {
                    window.__partsManualPublicationState = {
                        settled: false,
                        result: null,
                        error: null
                    };
                    window.__partsManualPublicationPromise =
                        window.__compareDbg.executeAgentTool({
                            name: 'generate_and_publish_parts_manual',
                            args: {
                                approval_mode: 'approve_trusted_ready_candidates',
                                layout_mode: 'generate_baseline_if_missing',
                                open_pdf: true
                            }
                        }, 'deviation-analyst');
                    window.__partsManualPublicationPromise.then(
                        result => {
                            window.__partsManualPublicationState.settled = true;
                            window.__partsManualPublicationState.result = result;
                        },
                        error => {
                            window.__partsManualPublicationState.settled = true;
                            window.__partsManualPublicationState.error = String(error);
                        }
                    );
                }"""
            )
            partial_seen = False
            progress_deadline = time.monotonic() + 360
            last_progress: dict[str, object] = {}
            while time.monotonic() < progress_deadline:
                observation = page.evaluate(
                    """() => ({
                        snapshot: window.__compareDbg.documentationGenerationSnapshot(),
                        settled: Boolean(window.__partsManualPublicationState?.settled),
                        error: window.__partsManualPublicationState?.error || null,
                        placeholderCount: document.querySelectorAll(
                            '#documentationPageList .documentation-page-generating'
                        ).length
                    })"""
                )
                last_progress = observation
                snapshot = observation.get("snapshot", {})
                if (
                    snapshot.get("working") is True
                    and 0 < snapshot.get("visiblePageCount", 0)
                    < snapshot.get("totalPageCount", 0)
                    and observation.get("placeholderCount") == 1
                ):
                    partial_seen = True
                    break
                if observation.get("settled"):
                    break
                page.wait_for_timeout(500)
            if not partial_seen and not last_progress.get("settled"):
                raise TimeoutError(
                    "Sage did not reach progressive page generation: "
                    + json.dumps(last_progress, sort_keys=True)
                )
            progressive_snapshot = page.evaluate(
                "() => window.__compareDbg.documentationGenerationSnapshot()"
            )
            stage_shadow = page.locator(
                "#documentationWorkspace .documentation-canvas-stage"
            ).evaluate("element => getComputedStyle(element).boxShadow")
            record(
                "sage_builds_pages_sequentially_inside_blue_viewport_frame",
                partial_seen
                and progressive_snapshot.get("working") is True
                and 0 < progressive_snapshot.get("visiblePageCount", 0)
                < progressive_snapshot.get("totalPageCount", 0)
                and "20, 143, 208" in stage_shadow
                and page.locator(
                    "#documentationWorkspace .documentation-sage-briefing"
                ).is_visible(),
                {
                    "snapshot": progressive_snapshot,
                    "stageBoxShadow": stage_shadow,
                },
            )
            page.screenshot(
                path=str(OUT / "sage_building_pages_in_documentation_viewport.png"),
                full_page=True,
            )

            result = page.evaluate(
                "async () => await window.__partsManualPublicationPromise"
            )
            generation_snapshot = page.evaluate(
                "() => window.__compareDbg.documentationGenerationSnapshot()"
            )
            page_events = [
                event
                for event in generation_snapshot.get("events", [])
                if event.get("type") == "page_revealed"
            ]
            record(
                "every_page_is_revealed_once_in_document_order",
                generation_snapshot.get("generationState") == "complete"
                and generation_snapshot.get("visiblePageCount")
                == generation_snapshot.get("totalPageCount")
                and len(page_events) == generation_snapshot.get("totalPageCount")
                and [event.get("index") for event in page_events]
                == list(range(len(page_events))),
                generation_snapshot,
            )
            report["toolResult"] = result
            (OUT / "tool_result_checkpoint.json").write_text(
                json.dumps(result, indent=2, sort_keys=True),
                encoding="utf-8",
            )
            print("TOOL RESULT " + json.dumps(result, sort_keys=True), flush=True)
            record(
                "tool_reaches_published_stage",
                result.get("ok") is True and result.get("stage") == "published",
                result,
            )
            if not (result.get("ok") is True and result.get("stage") == "published"):
                raise RuntimeError(
                    "Sage publication stopped before PDF creation: "
                    + json.dumps(result, sort_keys=True)
                )
            record(
                "tool_returns_complete_audit_proof",
                result.get("coveragePercent") == 100
                and result.get("manualPlanAudit", {}).get("status") == "PASS"
                and result.get("calloutAudit", {}).get("status") == "PASS"
                and result.get("passedCaptureCount")
                == result.get("requiredCaptureCount")
                and result.get("requiredCaptureCount", 0) > 0,
                {
                    "coverage": result.get("coveragePercent"),
                    "captures": [
                        result.get("passedCaptureCount"),
                        result.get("requiredCaptureCount"),
                    ],
                    "manualPlanAudit": result.get("manualPlanAudit", {}).get("status"),
                    "calloutAudit": result.get("calloutAudit", {}).get("status"),
                },
            )
            record(
                "every_capture_has_revision_bound_sha256",
                len(result.get("captureReceipts", []))
                == result.get("requiredCaptureCount")
                and all(
                    row.get("status") == "ready"
                    and row.get("qualityStatus") == "PASS"
                    and len(str(row.get("sha256") or "")) == 64
                    for row in result.get("captureReceipts", [])
                ),
                result.get("captureReceipts"),
            )
            record(
                "published_pdf_is_opened_in_app",
                result.get("opened") is True
                and page.locator("#manualPublishedPdfOverlay").count() == 1
                and page.locator("#manualPublishedPdfOverlay iframe").count() == 1,
            )

            page.evaluate("() => document.getElementById('manualPublishedPdfOverlay')?.remove()")
            page.locator(
                '#documentationPageList .documentation-page-item[title="Rear Wheel and Axle Assembly"]'
            ).click()
            accepted_capture = page.locator(
                "#documentationIllustrationFrame .documentation-accepted-capture"
            )
            accepted_capture.wait_for(state="visible", timeout=120_000)
            page.wait_for_function(
                """() => {
                    const workspace = document.getElementById('documentationWorkspace');
                    const image = document.querySelector(
                        '#documentationIllustrationFrame .documentation-accepted-capture.ready'
                    );
                    const callouts = document.querySelector(
                        '#documentationIllustrationFrame .documentation-publication-callouts.ready'
                    );
                    return Boolean(
                        workspace
                        && !workspace.classList.contains('busy')
                        && image?.complete
                        && image.naturalWidth > 0
                        && callouts
                    );
                }""",
                timeout=120_000,
            )
            preview_binding = page.evaluate(
                """() => {
                    const state = window.__compareDbg.state;
                    const active = state.partsManualDocumentation?.document?.pages?.find(
                        row => row.pageId === state.partsManualDocumentationPageId
                    );
                    const image = active?.renderRequest?.image || {};
                    const preview = document.querySelector(
                        '#documentationIllustrationFrame .documentation-accepted-capture'
                    );
                    return {
                        pageId: active?.pageId || null,
                        documentRevision: image.documentRevision || null,
                        artifactUrl: image.url || null,
                        previewUrl: preview?.getAttribute('src') || null,
                        manifestCalloutCount: (image.balloons || []).length,
                        previewCalloutCount: document.querySelectorAll(
                            '#documentationIllustrationFrame '
                            + '.documentation-publication-callouts > circle:not(.documentation-callout-end-dot)'
                        ).length,
                        previewLeaderCount: document.querySelectorAll(
                            '#documentationIllustrationFrame '
                            + '.documentation-publication-callouts > polyline'
                        ).length,
                    };
                }"""
            )
            record(
                "workspace_preview_uses_exact_revision_bound_publication_capture",
                preview_binding.get("pageId") is not None
                and preview_binding.get("documentRevision") == result.get("documentRevision")
                and preview_binding.get("artifactUrl") == preview_binding.get("previewUrl")
                and preview_binding.get("manifestCalloutCount") == 6
                and preview_binding.get("previewCalloutCount") == 6
                and preview_binding.get("previewLeaderCount", 0) >= 6,
                preview_binding,
            )
            page.screenshot(
                path=str(OUT / "workspace_matches_published_figure.png"),
                full_page=True,
            )

            pdf = result.get("pdf", {})
            response = request.get(
                f"{server.app_url}{pdf.get('url')}",
                timeout=120_000,
            )
            pdf_bytes = response.body()
            pdf_path = OUT / "sage_tricycle_illustrated_parts_manual.pdf"
            pdf_path.write_bytes(pdf_bytes)
            actual_sha256 = hashlib.sha256(pdf_bytes).hexdigest()
            document = fitz.open(stream=pdf_bytes, filetype="pdf")
            text = "\n".join(page.get_text() for page in document)
            record(
                "pdf_artifact_matches_receipt",
                response.ok
                and actual_sha256 == pdf.get("sha256")
                and len(pdf_bytes) == pdf.get("sizeBytes")
                and len(document) == pdf.get("pageCount"),
                {
                    "path": str(pdf_path),
                    "sha256": actual_sha256,
                    "bytes": len(pdf_bytes),
                    "pages": len(document),
                },
            )
            record(
                "pdf_contains_customer_facing_manual_sections",
                all(
                    value in text
                    for value in (
                        "Front Steering and Wheel Assembly",
                        "Frame and Seat Assembly",
                        "Rear Wheel and Axle Assembly",
                    )
                )
                and "__Parts Manual Smoke" not in text,
            )
            rear_page_text = document[6].get_text()
            record(
                "rear_assembly_uses_current_engineering_part_numbers",
                all(
                    value in rear_page_text
                    for value in (
                        "1030038",
                        "1030039",
                        "1030040",
                        "1030049",
                        "1030052",
                        "1030053",
                    )
                )
                and "Not specified" not in rear_page_text,
                rear_page_text,
            )

            current = request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}",
                timeout=120_000,
            ).json()
            record(
                "source_cad_identity_is_unchanged",
                current.get("sourceRevision") == initial_source_revision
                and result.get("sourceCadChanged") is False,
                {
                    "before": initial_source_revision,
                    "after": current.get("sourceRevision"),
                },
            )
            record(
                "no_browser_runtime_errors",
                not report["browserErrors"],
                report["browserErrors"],
            )
            page.screenshot(
                path=str(OUT / "published_pdf_open_in_inspectorpro.png"),
                full_page=True,
            )
            document.close()
            request.dispose()
            browser.close()
    except Exception as error:  # noqa: BLE001 - proof must persist diagnostics
        report["fatalError"] = f"{type(error).__name__}: {error}"
        print(report["fatalError"], file=sys.stderr)
    finally:
        server.stop()
        (OUT / "report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    return 0 if report["checks"] and all(
        row.get("ok") for row in report["checks"].values()
    ) and not report.get("fatalError") else 1


if __name__ == "__main__":
    raise SystemExit(run())
