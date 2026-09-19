"""End-to-end publication proof for the tricycle illustrated parts manual."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from urllib.parse import urlsplit

import fitz

from parts_manual_smoke_support import (
    IsolatedPartsManualServer,
    seed_internal_legacy_section,
)


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".runtime" / "parts_manual_publication_proof"
OUT.mkdir(parents=True, exist_ok=True)
ASSEMBLY = "tricycle"
PRODUCTION_PLAN_PATH = ROOT / "generated" / "parts_manual" / ASSEMBLY / "manual-plan.json"
EXPECTED_GROUPS = [
    "Front Steering and Wheel Assembly",
    "Frame and Seat Assembly",
    "Rear Wheel and Axle Assembly",
]
API_TIMEOUT_MS = 120_000


def _capture_render_page(page, assembly: str, document: dict, descriptor: dict) -> dict:
    """Capture one approved page through the production browser renderer."""

    return page.evaluate(
        """async ({ assembly, documentModel, targetPage }) => {
            const payload = window.__compareDbg?.state?.partsManualPayload;
            if (!payload) throw new Error('Parts Manual workspace payload is unavailable.');
            _partsManualViewDocumentPage(payload, targetPage);
            await _partsManualWaitForRenderPose();
            const capture = await _partsManualCaptureCurrentView(targetPage);
            const form = new FormData();
            form.append('documentRevision', documentModel.documentRevision);
            form.append('manualPlanRevision', documentModel.manualPlanRevision);
            form.append('sourceRevision', documentModel.sourceRevision);
            form.append('renderPipelineVersion', String(documentModel.renderPipelineVersion || ''));
            form.append('balloons', JSON.stringify(capture.balloons || []));
            form.append('file', capture.blob, `${targetPage.pageId}.png`);
            const response = await fetch(
                `/api/parts-manual/${encodeURIComponent(assembly)}`
                + `/document/${encodeURIComponent(targetPage.pageId)}/render`,
                { method: 'POST', body: form }
            );
            const stored = await response.json();
            if (!response.ok || stored.success === false) {
                throw new Error(stored.message || `Render storage failed (${response.status}).`);
            }
            return stored.artifact;
        }""",
        {
            "assembly": assembly,
            "documentModel": document,
            "targetPage": descriptor,
        },
    )


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    production_plan_before = (
        PRODUCTION_PLAN_PATH.read_bytes() if PRODUCTION_PLAN_PATH.is_file() else None
    )
    isolated_server = IsolatedPartsManualServer(ROOT, OUT, ASSEMBLY)
    report: dict[str, object] = {
        "appUrl": None,
        "assembly": ASSEMBLY,
        "repositoryMode": "isolated_temporary_server",
        "checks": {},
        "browserErrors": [],
        "failedResponses": [],
        "expectedUnavailableResponses": [],
        "unexpectedHttpFailures": [],
    }

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        message = f"{'PASS' if ok else 'FAIL'} {name}" + (
            f" :: {detail}" if not ok else ""
        )
        console_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        print(message.encode(
            console_encoding,
            errors="backslashreplace",
        ).decode(console_encoding))

    try:
        isolated_server.start()
        app_url = isolated_server.app_url
        report["appUrl"] = app_url
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1720, "height": 1080})
            page = context.new_page()
            api_request = playwright.request.new_context(
                base_url=app_url,
                timeout=API_TIMEOUT_MS,
            )
            page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))
            def observe_response(response) -> None:
                if response.status < 400:
                    return
                failure = {"status": response.status, "url": response.url}
                if "/api/parts-manual/" in response.url:
                    report["failedResponses"].append(failure)
                path = urlsplit(response.url).path
                expected_unavailable = (
                    response.status == 503
                    and path == "/api/agent/conversations"
                ) or (
                    response.status == 404
                    and path in {
                        f"/api/drawing-map/{ASSEMBLY}",
                        f"/api/drawing-pdf/{ASSEMBLY}",
                        f"/api/part-features/{ASSEMBLY}",
                    }
                )
                target = (
                    report["expectedUnavailableResponses"]
                    if expected_unavailable
                    else report["unexpectedHttpFailures"]
                )
                target.append(failure)

            page.on("response", observe_response)
            initial = seed_internal_legacy_section(api_request, app_url, ASSEMBLY)
            record(
                "isolated_legacy_fixture_seeded",
                len(initial.get("plan", {}).get("sections", [])) == 1
                and initial["plan"]["sections"][0].get("name") == "body",
                {"storeRoot": str(isolated_server.store_root)},
            )
            record(
                "legacy_manual_is_blocked_before_replacement",
                initial.get("publicationReadiness", {}).get("status") == "FAIL",
                initial.get("publicationReadiness"),
            )
            proposal_response = api_request.get(
                f"{app_url}/api/parts-manual/{ASSEMBLY}/proposal",
                timeout=API_TIMEOUT_MS,
            )
            proposal = proposal_response.json().get("proposal", {})
            ready = [row for row in proposal.get("candidates", []) if row.get("status") == "ready"]
            names = [row.get("name") for row in ready]
            record(
                "semantic_plan_covers_every_serviceable_occurrence",
                proposal_response.ok
                and proposal.get("summary", {}).get("coveragePercent") == 100
                and proposal.get("summary", {}).get("unassignedCount") == 0
                and names == EXPECTED_GROUPS,
                {"summary": proposal.get("summary"), "groups": names},
            )

            partial = api_request.post(
                f"{app_url}/api/parts-manual/{ASSEMBLY}/proposals/{proposal['proposalRevision']}/approve",
                data={
                    "baseRevision": initial["revision"],
                    "sourceRevision": initial["sourceRevision"],
                    "candidateIds": [ready[0]["candidateId"]],
                },
                timeout=API_TIMEOUT_MS,
            )
            after_partial = api_request.get(
                f"{app_url}/api/parts-manual/{ASSEMBLY}",
                timeout=API_TIMEOUT_MS,
            ).json()
            record(
                "partial_legacy_replacement_is_atomic_and_blocked",
                partial.status in {400, 409, 422}
                and after_partial.get("revision") == initial.get("revision"),
                {"status": partial.status, "body": partial.json()},
            )

            approval = api_request.post(
                f"{app_url}/api/parts-manual/{ASSEMBLY}/proposals/{proposal['proposalRevision']}/approve",
                data={
                    "baseRevision": initial["revision"],
                    "sourceRevision": initial["sourceRevision"],
                    "candidateIds": [row["candidateId"] for row in ready],
                },
                timeout=API_TIMEOUT_MS,
            )
            approval_body = approval.json()
            record(
                "semantic_groups_replace_internal_draft_in_one_transaction",
                approval.ok
                and set(row.get("name") for row in approval_body.get("sections", []))
                == set(EXPECTED_GROUPS)
                and approval_body.get("supersededSectionIds"),
                approval_body,
            )

            current = api_request.get(
                f"{app_url}/api/parts-manual/{ASSEMBLY}",
                timeout=API_TIMEOUT_MS,
            ).json()
            readiness = current.get("publicationReadiness", {})
            record(
                "publication_coverage_validator_passes",
                readiness.get("status") == "PASS"
                and readiness.get("eligibleOccurrenceCount") == 26
                and readiness.get("assignedOccurrenceCount") == 26
                and readiness.get("unassignedOccurrenceCount") == 0
                and readiness.get("multiplyAssignedOccurrenceCount") == 0
                and readiness.get("coveragePercent") == 100,
                readiness,
            )

            page.goto(
                f"{app_url}/?assemblyProfile={ASSEMBLY}",
                wait_until="domcontentloaded",
                timeout=90_000,
            )
            page.wait_for_function(
                """assembly => Boolean(
                    window.__compareDbg
                    && window.__compareDbg.state.partNumber === assembly
                    && window.__compareDbg.state.assyLiveScene
                    && window.__compareDbg.state.assyOccurrenceMeshMap
                )""",
                arg=ASSEMBLY,
                timeout=90_000,
            )

            page.get_by_role("button", name="Parts Manual", exact=True).click()
            manual = page.locator("#documentationWorkspace")
            manual.wait_for(state="visible", timeout=120_000)
            entry_snapshot = page.evaluate(
                "window.__compareDbg.documentationGenerationSnapshot()"
            )
            record(
                "ready_plan_entry_stays_blank_until_ai_arrange",
                entry_snapshot["workspaceOpen"]
                and entry_snapshot["blank"]
                and entry_snapshot["visiblePageCount"] == 0
                and entry_snapshot["totalPageCount"] == 8,
                entry_snapshot,
            )
            page.evaluate(
                """() => {
                    window.__partsManualBaselineResult = { status: 'running' };
                    window.__partsManualBaselinePromise = window.__compareDbg
                        .startDocumentationBaseline()
                        .then(value => {
                            window.__partsManualBaselineResult = { status: 'fulfilled' };
                            return value;
                        })
                        .catch(error => {
                            window.__partsManualBaselineResult = {
                                status: 'rejected',
                                message: String(error?.message || error),
                            };
                            return null;
                        });
                }"""
            )
            page.wait_for_function(
                """() => {
                    const generation = window.__compareDbg.documentationGenerationSnapshot();
                    return window.__partsManualBaselineResult?.status === 'rejected'
                        || (generation.generationState === 'complete'
                            && !generation.working
                            && generation.visiblePageCount === generation.totalPageCount);
                }""",
                timeout=300_000,
            )
            page.evaluate("() => window.__partsManualBaselinePromise")
            baseline_result = page.evaluate("window.__partsManualBaselineResult")
            if baseline_result.get("status") == "rejected":
                raise RuntimeError(
                    "Parts-manual baseline generation failed: "
                    f"{baseline_result}"
                )
            page_titles = manual.locator(
                ".documentation-page-item"
            ).evaluate_all("rows => rows.map(row => row.title)")
            section_text = [title for title in page_titles if title in EXPECTED_GROUPS]
            summary_text = manual.locator(".documentation-statusbar").inner_text()
            record(
                "manual_plan_ui_shows_publishable_structure",
                section_text == EXPECTED_GROUPS
                and len(page_titles) == 8
                and page.locator("#documentationPublishRibbon").count() == 1,
                {
                    "sections": section_text,
                    "pageTitles": page_titles,
                    "status": summary_text,
                },
            )

            document_before = api_request.get(
                f"{app_url}/api/parts-manual/{ASSEMBLY}/document",
                timeout=API_TIMEOUT_MS,
            ).json()["document"]
            page_types = [row["pageType"] for row in document_before["pages"]]
            record(
                "document_model_is_eight_page_oem_structure",
                document_before["pageCount"] == 8
                and page_types == [
                    "cover",
                    "document_information",
                    "table_of_contents",
                    "assembly_overview",
                    "manual_section",
                    "manual_section",
                    "manual_section",
                    "parts_index",
                ]
                and document_before["documentNumber"] == "IPM-TRICYCLE-001"
                and document_before["revision"] == "A",
                {"pageCount": document_before["pageCount"], "pageTypes": page_types},
            )

            baseline_document_revision = document_before["documentRevision"]
            page.locator(
                '.documentation-page-item[title="Front Steering and Wheel Assembly"]'
            ).click()
            page.wait_for_function(
                """() => Boolean(
                    document.querySelector(
                        '#documentationPublicationSurface .documentation-page-header-title'
                    )
                        ?.textContent.includes('FIGURE 2-1')
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=120_000,
            )
            inspector_button = page.locator("#documentationInspectorRibbon")
            if inspector_button.is_visible():
                inspector_button.click()
            else:
                page.locator("#documentationOverflowMenuRibbon").click()
                page.locator(
                    '.documentation-overflow-section[data-overflow-group="workspace"] '
                    '.documentation-menu-item',
                    has_text="Inspector",
                ).click()
            page.wait_for_function(
                """() => document.querySelector('#documentationWorkspace')
                    ?.classList.contains('inspector-open') === true""",
                timeout=30_000,
            )
            page.locator(
                ".documentation-target-row",
                has_text="Bill of materials",
            ).click()
            bom = page.locator("#documentationPageSidecar")
            before_drag = bom.bounding_box()
            page.mouse.move(
                before_drag["x"] + before_drag["width"] * 0.5,
                before_drag["y"] + before_drag["height"] * 0.5,
            )
            page.mouse.down()
            page.mouse.move(
                before_drag["x"] + before_drag["width"] * 0.5 + 14,
                before_drag["y"] + before_drag["height"] * 0.5 + 8,
                steps=4,
            )
            page.mouse.up()
            page.wait_for_function(
                """() => Boolean(
                    window.__compareDbg.state.partsManualDocumentation?.scene?.pages?.[
                        window.__compareDbg.state.partsManualDocumentationPageId
                    ]?.pageElementOverrides?.bom
                    && !document.querySelector('#documentationWorkspace.busy')
                )""",
                timeout=30_000,
            )
            edited_page_id = page.evaluate(
                "window.__compareDbg.state.partsManualDocumentationPageId"
            )
            edited_scene_payload = api_request.get(
                f"{app_url}/api/parts-manual/{ASSEMBLY}/documentation-scene",
                timeout=API_TIMEOUT_MS,
            ).json()
            edited_scene = edited_scene_payload["scene"]
            bom_override = edited_scene["pages"][edited_page_id][
                "pageElementOverrides"
            ]["bom"]
            document_before = api_request.get(
                f"{app_url}/api/parts-manual/{ASSEMBLY}/document",
                timeout=API_TIMEOUT_MS,
            ).json()["document"]
            edited_page = next(
                row for row in document_before["pages"] if row["pageId"] == edited_page_id
            )
            record(
                "documentation_override_changes_the_publication_revision_and_page_model",
                document_before["documentRevision"] != baseline_document_revision
                and document_before["documentationSceneRevision"]
                == edited_scene_payload["revision"]
                and edited_page["renderRequest"]["composition"]["pageElementOverrides"][
                    "bom"
                ] == bom_override,
                {
                    "baselineDocumentRevision": baseline_document_revision,
                    "editedDocumentRevision": document_before["documentRevision"],
                    "documentationSceneRevision": edited_scene_payload["revision"],
                    "pageId": edited_page_id,
                    "bomOverride": bom_override,
                },
            )

            capture_artifacts = []
            for descriptor in document_before["pages"]:
                if not descriptor.get("renderRequest"):
                    continue
                print(f"CAPTURE start {descriptor['pageId']} :: {descriptor['title']}")
                artifact = _capture_render_page(
                    page,
                    ASSEMBLY,
                    document_before,
                    descriptor,
                )
                capture_artifacts.append(artifact)
                print(f"CAPTURE pass {descriptor['pageId']} :: {descriptor['title']}")
            record(
                "browser_renderer_captures_every_technical_page",
                len(capture_artifacts) == 5
                and all(row.get("status") == "ready" for row in capture_artifacts),
                capture_artifacts,
            )
            document_after = api_request.get(
                f"{app_url}/api/parts-manual/{ASSEMBLY}/document",
                timeout=API_TIMEOUT_MS,
            ).json()["document"]
            renderable = [row for row in document_after["pages"] if row.get("renderRequest")]
            render_qa = []
            for row in renderable:
                image = row["renderRequest"]["image"]
                expected_items = row["renderRequest"].get("calloutItems", [])
                render_qa.append(
                    {
                        "pageId": row["pageId"],
                        "status": image.get("status"),
                        "quality": image.get("quality"),
                        "calloutQuality": (image.get("quality") or {}).get("calloutQuality"),
                        "expectedBalloons": len(expected_items),
                        "actualBalloons": len(image.get("balloons", [])),
                    }
                )
            record(
                "all_technical_illustrations_pass_framing_and_balloon_qa",
                len(renderable) == 5
                and all(
                    row["status"] == "ready"
                    and row["quality"].get("status") == "PASS"
                    and row["quality"].get("foregroundOccupancyMetric") == "bounding_box_area"
                    and (
                        0.38 <= row["quality"].get("foregroundOccupancy", 0) <= 0.72
                        if row["pageId"] == "page-cover"
                        else (
                            0.60 <= row["quality"].get("foregroundOccupancy", 0) <= 0.80
                            or (
                                row["quality"].get("axisConstrainedOccupancyAccepted") is True
                                and 0.50
                                <= row["quality"].get("foregroundOccupancy", 0)
                                <= 0.80
                            )
                        )
                    )
                    and row["expectedBalloons"] == row["actualBalloons"]
                    and (
                        row["expectedBalloons"] == 0
                        or (
                            row["calloutQuality"].get("status") == "PASS"
                            and row["calloutQuality"].get("anchorMethod")
                            == "frontmost_camera_raycast"
                            and row["calloutQuality"].get("leaderStyle")
                            == "auto_straight_first"
                            and row["calloutQuality"].get(
                                "balloonCircumferenceAttachmentCount"
                            ) == row["expectedBalloons"]
                            and row["calloutQuality"].get(
                                "maximumAutomaticElbowCount", 99
                            ) <= 1
                            and row["calloutQuality"].get("routeValidationMethod")
                            == "frontmost_raycast_sampling"
                            and row["calloutQuality"].get("routeRaycastSampleCount", 0) > 0
                            and row["calloutQuality"].get("leaderCrossingCount") == 0
                            and row["calloutQuality"].get("geometryIntersectionCount") == 0
                            and row["calloutQuality"].get(
                                "leaderBalloonCollisionCount"
                            ) == 0
                            and row["calloutQuality"].get(
                                "nearParallelCongestionCount"
                            ) == 0
                            and row["calloutQuality"].get(
                                "maximumVisibleLeaderLength", 1
                            ) <= 0.35
                        )
                    )
                    for row in render_qa
                ),
                render_qa,
            )

            page.screenshot(path=str(OUT / "manual_publication_workspace.png"), full_page=False)
            pdf_response = api_request.post(
                f"{app_url}/api/parts-manual/{ASSEMBLY}/pdf",
                data={
                    "documentRevision": document_after["documentRevision"],
                    "manualPlanRevision": document_after["manualPlanRevision"],
                    "sourceRevision": document_after["sourceRevision"],
                },
                timeout=API_TIMEOUT_MS,
            )
            if not pdf_response.ok:
                raise RuntimeError(
                    f"PDF generation failed ({pdf_response.status}): {pdf_response.text()}"
                )
            pdf_artifact = pdf_response.json()["artifact"]
            artifact_url = str(pdf_artifact["url"])
            if artifact_url.startswith("/"):
                artifact_url = f"{app_url}{artifact_url}"
            pdf_download = api_request.get(artifact_url, timeout=API_TIMEOUT_MS)
            if not pdf_download.ok:
                raise RuntimeError(f"PDF download failed ({pdf_download.status}).")
            pdf_path = OUT / "tricycle_illustrated_parts_manual.pdf"
            pdf_path.write_bytes(pdf_download.body())
            record(
                "documentation_edit_capture_publish_chain_uses_current_revision",
                document_after["documentRevision"] == document_before["documentRevision"]
                and all(
                    row.get("documentRevision") == document_after["documentRevision"]
                    for row in capture_artifacts
                )
                and pdf_artifact.get("documentRevision")
                == document_after["documentRevision"]
                and pdf_path.stat().st_size > 0,
                {
                    "documentRevision": document_after["documentRevision"],
                    "captureRevisions": sorted(
                        {row.get("documentRevision") for row in capture_artifacts}
                    ),
                    "pdfDocumentRevision": pdf_artifact.get("documentRevision"),
                    "pdfBytes": pdf_path.stat().st_size,
                },
            )

            with fitz.open(pdf_path) as pdf:
                text = "\n".join(pdf_page.get_text() for pdf_page in pdf)
                bookmarks = pdf.get_toc()
                page_drawings = [len(pdf_page.get_drawings()) for pdf_page in pdf]
                balloon_label_checks = []
                bom_clearance_checks = []
                bom_part_number_checks = []
                brand_wordmark_checks = []
                for descriptor in document_after["pages"]:
                    page_index = int(descriptor["pageNumber"]) - 1
                    pdf_page = pdf[page_index]
                    words = [word[4] for word in pdf_page.get_text("words")]
                    spans = [
                        span
                        for block in pdf_page.get_text("dict").get("blocks", [])
                        for line in block.get("lines", [])
                        for span in line.get("spans", [])
                    ]
                    inspector_spans = [span for span in spans if span.get("text") == "Inspector"]
                    pro_spans = [span for span in spans if span.get("text") == "Pro"]
                    brand_wordmark_checks.append(
                        {
                            "pageId": descriptor["pageId"],
                            "splitColorWordmark": bool(inspector_spans and pro_spans)
                            and inspector_spans[0].get("color") != pro_spans[0].get("color"),
                        }
                    )
                    callouts = descriptor.get("renderRequest", {}).get("calloutItems", [])
                    if callouts:
                        balloon_label_checks.append(
                            {
                                "pageId": descriptor["pageId"],
                                "visible": all(
                                    words.count(str(item["itemNumber"])) >= 2
                                    for item in callouts
                                ),
                            }
                        )
                    if descriptor.get("pageType") == "manual_section":
                        for row in descriptor.get("bom") or []:
                            display_part_number = str(
                                row.get("displayPartNumber")
                                or row.get("engineeringPartNumber")
                                or ""
                            ).strip()
                            bom_part_number_checks.append(
                                {
                                    "pageId": descriptor["pageId"],
                                    "item": row.get("item"),
                                    "partNumber": display_part_number,
                                    "assigned": bool(display_part_number)
                                    and display_part_number != "Not specified",
                                }
                            )
                            matches = pdf_page.search_for(str(row.get("description") or ""))
                            bom_clearance_checks.append(
                                {
                                    "pageId": descriptor["pageId"],
                                    "item": row.get("item"),
                                    "insideSafeRegion": bool(matches)
                                    and all(match.y1 < pdf_page.rect.height - 48 for match in matches),
                                }
                            )
                for index, pdf_page in enumerate(pdf):
                    pixmap = pdf_page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False)
                    pixmap.save(OUT / f"page-{index + 1:02d}.png")
                record(
                    "generated_pdf_passes_publication_content_qa",
                    pdf.page_count == 8
                    and "ILLUSTRATED PARTS MANUAL" in text
                    and "IPM-TRICYCLE-001" in text
                    and all(name in text for name in EXPECTED_GROUPS)
                    and all(f"Figure {value}-1" in text for value in range(1, 5))
                    and "PART NUMBER INDEX" in text
                    and "body" not in text
                    and "Smoke" not in text
                    and "Revision: -" not in text
                    and len(bookmarks) >= 6
                    and all(page_drawings[index] > 0 for index in range(3, 7)),
                    {
                        "pageCount": pdf.page_count,
                        "bookmarkCount": len(bookmarks),
                        "pageDrawingCounts": page_drawings,
                        "byteLength": pdf_path.stat().st_size,
                    },
                )
                record(
                    "pdf_visual_composition_contract_passes",
                    "Assembly Assembly" not in text
                    and "SWPR-Tricycle_" not in text
                    and "Grip2" not in text
                    and "Fork2" not in text
                    and bom_part_number_checks
                    and all(row["assigned"] for row in bom_part_number_checks)
                    and balloon_label_checks
                    and all(row["visible"] for row in balloon_label_checks)
                    and bom_clearance_checks
                    and all(row["insideSafeRegion"] for row in bom_clearance_checks)
                    and brand_wordmark_checks
                    and all(row["splitColorWordmark"] for row in brand_wordmark_checks),
                    {
                        "balloonLabels": balloon_label_checks,
                        "bomClearance": bom_clearance_checks,
                        "bomPartNumbers": bom_part_number_checks,
                        "brandWordmarks": brand_wordmark_checks,
                    },
                )
            record("no_browser_errors", not report["browserErrors"], report["browserErrors"])
            record(
                "no_unexpected_browser_api_failures",
                not report["failedResponses"] and not report["unexpectedHttpFailures"],
                {
                    "partsManualFailures": report["failedResponses"],
                    "unexpectedHttpFailures": report["unexpectedHttpFailures"],
                    "expectedUnavailableResponses": report[
                        "expectedUnavailableResponses"
                    ],
                },
            )
            api_request.dispose()
            browser.close()
    except Exception as exc:  # noqa: BLE001
        report["exception"] = str(exc)
        console_encoding = getattr(sys.stdout, "encoding", None) or "utf-8"
        safe_exception = str(exc).encode(
            console_encoding,
            errors="backslashreplace",
        ).decode(console_encoding)
        print(f"FAIL smoke_exception :: {safe_exception}")
    finally:
        isolated_plan = isolated_server.plan_path if isolated_server.store_root else None
        isolated_plan_exists = bool(isolated_plan and isolated_plan.is_file())
        if isolated_plan_exists and isolated_plan is not None:
            (OUT / "isolated_manual_plan.json").write_bytes(isolated_plan.read_bytes())
        isolated_server.stop()
        production_plan_after = (
            PRODUCTION_PLAN_PATH.read_bytes() if PRODUCTION_PLAN_PATH.is_file() else None
        )
        record(
            "proof_uses_isolated_plan_store",
            isolated_plan_exists
            and isolated_server.store_root is not None
            and isolated_server.store_root.resolve()
            != (ROOT / "generated" / "parts_manual").resolve(),
        )
        record(
            "production_manual_plan_untouched",
            production_plan_after == production_plan_before,
        )
        report_path = OUT / "publication_proof.json"
        report_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"Report: {report_path}")

    return 0 if all(
        bool(value.get("ok")) for value in report["checks"].values()
    ) and "exception" not in report else 1


if __name__ == "__main__":
    raise SystemExit(run())
