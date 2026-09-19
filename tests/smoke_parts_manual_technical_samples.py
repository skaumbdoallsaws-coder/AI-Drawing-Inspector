"""Four-stage visual proof for technical illustrated-parts pages.

This deliberately does not generate the complete illustrated-parts PDF.
"""

from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import sys

import fitz

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.parts_manual.pdf import (
    _draw_balloons,
    _draw_bom_table,
    _draw_footer,
    _draw_header,
    _draw_image,
    _fit_text,
)
from parts_manual_smoke_support import IsolatedPartsManualServer


OUT = ROOT / ".runtime" / "parts_manual_technical_samples"
ASSEMBLY = "tricycle"
FRONT_TITLE = "Front Steering and Wheel Assembly"


def _rasterize(pdf: fitz.Document, output: Path) -> None:
    pixmap = pdf[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
    pixmap.save(output)
    pdf.close()


def _new_page() -> tuple[fitz.Document, fitz.Page]:
    pdf = fitz.open()
    return pdf, pdf.new_page(width=792, height=612)


def _manual_section_sample(
    document: dict,
    descriptor: dict,
    image_path: Path,
    output: Path,
    *,
    draw_callouts: bool,
    bom_rows: list[dict] | None = None,
    image_override: dict | None = None,
) -> None:
    pdf, page = _new_page()
    _draw_header(fitz, page, descriptor, document, ROOT, ASSEMBLY)
    image = image_override or descriptor["renderRequest"]["image"]
    rows = descriptor.get("bom") if bom_rows is None else bom_rows
    image_rect = _draw_image(fitz, page, image_path, fitz.Rect(28, 62, 544, 564), image)
    if draw_callouts:
        _draw_balloons(fitz, page, image_rect, image)
    _draw_bom_table(fitz, page, fitz.Rect(558, 70, 764, 564), rows or [])
    _draw_footer(fitz, page, document, descriptor)
    _rasterize(pdf, output)


def _overview_sample(
    document: dict,
    descriptor: dict,
    image_path: Path,
    output: Path,
) -> None:
    pdf, page = _new_page()
    _draw_header(fitz, page, descriptor, document, ROOT, ASSEMBLY)
    image = descriptor["renderRequest"]["image"]
    image_rect = _draw_image(fitz, page, image_path, fitz.Rect(30, 62, 575, 564), image)
    _draw_balloons(fitz, page, image_rect, image)
    page.insert_textbox(
        fitz.Rect(592, 68, 764, 90),
        "ILLUSTRATED GROUP INDEX",
        fontsize=9.2,
        fontname="hebo",
        color=(0.05, 0.33, 0.53),
    )
    y = 98.0
    for group in descriptor.get("manualGroupItems") or []:
        page.draw_circle(
            fitz.Point(605, y + 14),
            9,
            color=(0.04, 0.35, 0.57),
            fill=(1, 1, 1),
            width=1,
        )
        label = str(group.get("itemNumber") or "")
        width = fitz.get_text_length(label, fontname="hebo", fontsize=7.5)
        page.insert_text(
            fitz.Point(605 - width * 0.5, y + 16.6),
            label,
            fontsize=7.5,
            fontname="hebo",
            color=(0.03, 0.20, 0.31),
        )
        _fit_text(
            fitz,
            page,
            fitz.Rect(620, y + 4, 764, y + 20),
            group.get("name"),
            fontsize=7.8,
            fontname="hebo",
        )
        page.insert_textbox(
            fitz.Rect(620, y + 22, 764, y + 37),
            f"Figure {group.get('figureNumber')} | Page {group.get('pageNumber')}",
            fontsize=6.8,
            fontname="helv",
            color=(0.35, 0.42, 0.47),
        )
        y += 46
    _draw_footer(fitz, page, document, descriptor)
    _rasterize(pdf, output)


def _capture(page, assembly: str, page_id: str) -> dict:
    return page.evaluate(
        """async ({ assembly, pageId }) => {
            const manualResponse = await fetch(`/api/parts-manual/${encodeURIComponent(assembly)}`);
            const payload = await manualResponse.json();
            const documentResponse = await fetch(`/api/parts-manual/${encodeURIComponent(assembly)}/document`);
            const documentPayload = await documentResponse.json();
            const documentModel = documentPayload.document;
            const targetPage = documentModel.pages.find(value => value.pageId === pageId);
            if (!targetPage) throw new Error(`Missing manual page ${pageId}`);
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
            const storedResponse = await fetch(
                `/api/parts-manual/${encodeURIComponent(assembly)}/document/${encodeURIComponent(targetPage.pageId)}/render`,
                { method: 'POST', body: form }
            );
            const stored = await storedResponse.json();
            if (!storedResponse.ok) {
                throw new Error(stored.message || `Render storage failed (${storedResponse.status})`);
            }
            const bytes = new Uint8Array(await capture.blob.arrayBuffer());
            let binary = '';
            const chunkSize = 0x8000;
            for (let offset = 0; offset < bytes.length; offset += chunkSize) {
                binary += String.fromCharCode(...bytes.subarray(offset, offset + chunkSize));
            }
            return {
                pngBase64: btoa(binary),
                artifact: stored.artifact,
                balloons: capture.balloons,
                documentRevision: documentModel.documentRevision,
            };
        }""",
        {"assembly": assembly, "pageId": page_id},
    )


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    front_only = "--front-only" in sys.argv[1:]
    rear_only = "--rear-only" in sys.argv[1:]
    OUT.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "assembly": ASSEMBLY,
        "fullPdfGenerated": False,
        "frontOnly": front_only,
        "rearOnly": rear_only,
        "browserErrors": [],
        "checks": {},
    }

    def check(name: str, passed: bool, detail=None) -> None:
        report["checks"][name] = {"passed": bool(passed), "detail": detail}
        print(f"{'PASS' if passed else 'FAIL'} {name}")
        if not passed:
            raise RuntimeError(f"{name} failed: {detail}")

    server = IsolatedPartsManualServer(ROOT, OUT, ASSEMBLY)
    try:
        server.start()
        report["appUrl"] = server.app_url
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = browser.new_context(viewport={"width": 1720, "height": 1080})
            page = context.new_page()
            page.on("pageerror", lambda error: report["browserErrors"].append(str(error)))
            page.goto(
                f"{server.app_url}/?assemblyProfile={ASSEMBLY}",
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
            slender_fixture = page.evaluate(
                """() => {
                    const camera = new THREE.OrthographicCamera(-2, 2, 2, -2, 0.1, 20);
                    camera.position.set(0, 0, 6);
                    camera.lookAt(0, 0, 0);
                    camera.updateProjectionMatrix();
                    camera.updateMatrixWorld(true);
                    const geometry = new THREE.BoxGeometry(3.2, 0.002, 0.02);
                    const material = new THREE.MeshBasicMaterial({ color: 0xffffff });
                    const mesh = new THREE.Mesh(geometry, material);
                    mesh.rotation.z = Math.PI * 0.173;
                    mesh.position.set(0.017, -0.013, 0);
                    mesh.updateMatrixWorld(true);
                    const bounds = _partsManualProjectedBounds([mesh], camera);
                    const samples = _partsManualVisibleAnchorSamples(
                        [mesh], bounds, camera, [mesh], 'slender-fixture'
                    );
                    const result = {
                        bounds,
                        sampleCount: samples.length,
                        silhouetteCount: samples.filter(value => value.onSilhouette).length,
                        samplingPassCount: Number(samples[0]?.samplingPassCount || 0),
                        samplingProbeCount: Number(samples[0]?.samplingProbeCount || 0),
                        samplingDivisions: Number(samples[0]?.samplingDivisions || 0),
                        adaptiveSamplingUsed: Boolean(samples[0]?.adaptiveSamplingUsed),
                        maximumProbeCount: PARTS_MANUAL_ANCHOR_SAMPLING_MAX_PROBES,
                    };
                    geometry.dispose();
                    material.dispose();
                    return result;
                }"""
            )
            check(
                "adaptive_silhouette_sampling_resolves_a_slender_fixture_within_its_bound",
                slender_fixture["sampleCount"] > 0
                and slender_fixture["silhouetteCount"] > 0
                and slender_fixture["adaptiveSamplingUsed"]
                and 2 <= slender_fixture["samplingPassCount"] <= 3
                and slender_fixture["samplingProbeCount"]
                    <= slender_fixture["maximumProbeCount"],
                slender_fixture,
            )
            initial = page.request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}"
            ).json()
            proposal = page.request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/proposal"
            ).json()["proposal"]
            ready = [row for row in proposal.get("candidates") or [] if row.get("status") == "ready"]
            approval = page.request.post(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/proposals/{proposal['proposalRevision']}/approve",
                data={
                    "baseRevision": initial["revision"],
                    "sourceRevision": initial["sourceRevision"],
                    "candidateIds": [row["candidateId"] for row in ready],
                },
            )
            check(
                "semantic_manual_plan_approved",
                approval.ok,
                {"status": approval.status, "candidateCount": len(ready)},
            )
            document = page.request.get(
                f"{server.app_url}/api/parts-manual/{ASSEMBLY}/document"
            ).json()["document"]
            front = next(row for row in document["pages"] if row.get("title") == FRONT_TITLE)
            overview = next(row for row in document["pages"] if row.get("pageType") == "assembly_overview")
            if rear_only:
                rear = next(
                    row
                    for row in document["pages"]
                    if row.get("title") == "Rear Wheel and Axle Assembly"
                )
                rear_capture = _capture(page, ASSEMBLY, rear["pageId"])
                rear_png = OUT / "rear-framing-regression.png"
                rear_png.write_bytes(base64.b64decode(rear_capture["pngBase64"]))
                rear_quality = rear_capture["artifact"].get("quality") or {}
                rear_callout_quality = rear_quality.get("calloutQuality") or {}
                rear_occupancy = rear_quality.get("foregroundOccupancy", 0)
                check(
                    "rear_module_camera_and_framing_pass",
                    rear_quality.get("status") == "PASS"
                    and rear_occupancy <= 0.80
                    and (
                        rear_occupancy >= 0.60
                        or (
                            rear_quality.get("axisConstrainedOccupancyAccepted") is True
                            and rear_occupancy >= 0.50
                        )
                    )
                    and rear_callout_quality.get("status") == "PASS"
                    and rear_callout_quality.get("maximumVisibleLeaderLength", 1) <= 0.35
                    and rear_callout_quality.get("leaderBalloonCollisionCount", 99) == 0
                    and rear_callout_quality.get("nearParallelCongestionCount", 99) == 0
                    and rear_callout_quality.get("frameClipBalloonCount", 99) == 0
                    and rear_callout_quality.get("minimumBalloonGap", 0) >= 0.075
                    and rear_callout_quality.get(
                        "repeatedItemsWithoutIndication", [1]
                    ) == []
                    # Automatic generation gives every repeated part one balloon,
                    # one leader and an nX badge - never a split Y-shaped leader.
                    and rear_callout_quality.get("branchedCalloutCount", 99) == 0
                    and rear_callout_quality.get("branchCount", 99) == 0
                    # Automatic leaders terminate on a dot, never an arrowhead.
                    and rear_callout_quality.get("arrowEndConditionCount", 99) == 0
                    and rear_callout_quality.get("dotEndConditionCount", 0)
                        == rear_callout_quality.get("balloonCount", -1),
                    rear_quality,
                )
                context.close()
                browser.close()
                return 0
            check(
                "hlr_is_default",
                front["renderRequest"]["illustrationStyle"] == "HIDDEN_LINES_REMOVED"
                and overview["renderRequest"]["illustrationStyle"] == "HIDDEN_LINES_REMOVED",
            )

            try:
                front_capture = _capture(page, ASSEMBLY, front["pageId"])
            except Exception:
                page.screenshot(path=OUT / "front-capture-failure.png", full_page=True)
                failure_diagnostics = page.evaluate(
                    """() => ({
                        route: window.__compareDbg.state.partsManualRouteQaDiagnostics || null,
                        visibilityRepair:
                            window.__compareDbg.state.partsManualExplodeVisibilityDiagnostics || [],
                        projectedCallouts: (() => {
                            const state = window.__compareDbg.state;
                            const camera = state.assyCamera;
                            const rows = (state.partsManualCallouts || []).map(callout => {
                                const meshes = [...new Set(
                                    (callout.targetMeshGroups || []).flatMap(group => group.meshes || [])
                                )].filter(mesh => mesh?.isMesh);
                                return {
                                    itemNumber: Number(callout.itemNumber || 0),
                                    bounds: _partsManualProjectedBounds(meshes, camera),
                                    meshes,
                                };
                            });
                            return rows.map(row => ({
                                itemNumber: row.itemNumber,
                                bounds: row.bounds,
                                overlapByItem: rows
                                    .filter(other => other !== row)
                                    .map(other => ({
                                        itemNumber: other.itemNumber,
                                        ratio: _partsManualProjectedOverlapRatio(
                                            row.bounds,
                                            other.bounds
                                        ),
                                    }))
                                    .filter(overlap => overlap.ratio > 0)
                                    .sort((left, right) => right.ratio - left.ratio),
                            }));
                        })(),
                        captureStages:
                            window.__compareDbg.state.partsManualCaptureDiagnostics || null,
                    })"""
                )
                (OUT / "front-capture-failure.json").write_text(
                    json.dumps(failure_diagnostics, indent=2), encoding="utf-8"
                )
                raise
            front_png = OUT / "test-01-hlr-only.png"
            front_png.write_bytes(base64.b64decode(front_capture["pngBase64"]))
            front["renderRequest"]["image"] = front_capture["artifact"]
            front_quality = front_capture["artifact"].get("quality") or {}
            check(
                "test_1_hlr_render_passes",
                front_quality.get("status") == "PASS"
                and front_quality.get("illustrationStyle") == "HIDDEN_LINES_REMOVED"
                and front_quality.get("coloredForegroundPercent", 100) <= 2,
                front_quality,
            )

            _manual_section_sample(
                document,
                front,
                front_png,
                OUT / "test-02-hlr-simple-bom.png",
                draw_callouts=False,
            )
            _manual_section_sample(
                document,
                front,
                front_png,
                OUT / "test-03-hlr-straight-first-callouts.png",
                draw_callouts=True,
            )
            front_balloons = front_capture["artifact"].get("balloons") or []
            branched = [row for row in front_balloons if row.get("calloutType") == "branched"]
            representative = [
                row
                for row in front_balloons
                if row.get("calloutType") == "representative_with_count"
            ]
            repeated_rows_by_item = {
                int(row.get("item") or 0): int(row.get("quantity") or 0)
                for row in front.get("bom") or []
                if int(row.get("quantity") or 0) > 1
            }
            repeated_callouts = [
                row
                for row in front_balloons
                if int(row.get("itemNumber") or 0) in repeated_rows_by_item
            ]
            front_callout_quality = front_quality.get("calloutQuality") or {}
            check(
                "test_3_callout_qa_passes",
                front_callout_quality.get("status") == "PASS"
                and all(
                    row.get("leaderStyle") in {"straight", "orthogonal"}
                    for row in front_balloons
                )
                and all(row.get("balloonAttachment") for row in front_balloons),
                front_callout_quality,
            )
            recomputed = front_callout_quality.get("serverRecomputedMetrics") or {}
            validated = front_callout_quality.get(
                "clientValidatedGeometryEvidence"
            ) or {}
            check(
                "callout_qa_reports_metric_provenance_without_overclaiming_geometry",
                "metricSource" not in front_callout_quality
                and recomputed.get("balloonCount") == len(front_balloons)
                and recomputed.get("leaderCrossingCount") == 0
                and validated.get("anchorMethod") == "frontmost_camera_raycast"
                and validated.get("routeRaycastSampleCount", 0) > 0
                and "reportedGeometryIntersectionCount" in validated,
                {
                    "serverRecomputedMetrics": recomputed,
                    "clientValidatedGeometryEvidence": validated,
                },
            )
            check(
                "test_3_callouts_are_compact_and_uncongested",
                front_callout_quality.get("maximumVisibleLeaderLength", 1) <= 0.35
                and front_callout_quality.get("maximumLeaderDetourRatio", 99) <= 1.75
                and front_callout_quality.get("frameClipBalloonCount", 99) == 0
                and front_callout_quality.get("minimumBalloonGap", 0) >= 0.075
                and front_callout_quality.get("maximumElbowCount", 99) <= 2
                and front_callout_quality.get(
                    "repeatedItemsWithoutIndication", [1]
                ) == []
                and front_callout_quality.get("leaderBalloonCollisionCount", 99) == 0
                and front_callout_quality.get("nearParallelCongestionCount", 99) == 0
                # Automatic generation gives every repeated part one balloon,
                # one leader and an nX badge - never a split Y-shaped leader.
                and front_callout_quality.get("branchedCalloutCount", 99) == 0
                and front_callout_quality.get("branchCount", 99) == 0
                # Automatic leaders terminate on a dot, never an arrowhead.
                and front_callout_quality.get("arrowEndConditionCount", 99) == 0
                and front_callout_quality.get("dotEndConditionCount", 0)
                    == front_callout_quality.get("balloonCount", -1),
                front_callout_quality,
            )
            check(
                # Every automatically generated qty>1 item: one balloon, one
                # leader, one representative anchor, an nX badge matching the BOM
                # QTY, and no branches at all.
                "repeated_parts_use_one_counted_representative_leader",
                len(repeated_callouts) == len(repeated_rows_by_item)
                and all(
                    row.get("calloutType") == "representative_with_count"
                    and not row.get("branches")
                    and len(row.get("anchors") or []) == 1
                    and int(row.get("representativeCount") or 0)
                    == repeated_rows_by_item[int(row.get("itemNumber") or 0)]
                    and row.get("quantityLabel")
                    == f"{repeated_rows_by_item[int(row.get('itemNumber') or 0)]}X"
                    for row in repeated_callouts
                ),
                {
                    "balloons": [
                        {
                            "itemNumber": row.get("itemNumber"),
                            "calloutType": row.get("calloutType"),
                            "branches": len(row.get("branches") or []),
                            "anchors": len(row.get("anchors") or []),
                            "representativeCount": row.get("representativeCount"),
                            "quantityLabel": row.get("quantityLabel"),
                        }
                        for row in front_balloons
                    ],
                    "routing": None if repeated_callouts else page.evaluate(
                        "window.__compareDbg.state.partsManualRouteQaDiagnostics"
                    ),
                },
            )
            repeated = (branched or representative)[0]
            repeated_item = int(repeated["itemNumber"])
            repeated_rows = [row for row in front.get("bom") or [] if int(row.get("item") or 0) == repeated_item]
            repeated_image = copy.deepcopy(front_capture["artifact"])
            repeated_image["balloons"] = [repeated]
            _manual_section_sample(
                document,
                front,
                front_png,
                OUT / "test-04a-repeated-branched-leader.png",
                draw_callouts=True,
                bom_rows=repeated_rows,
                image_override=repeated_image,
            )

            if front_only:
                context.close()
                browser.close()
                return 0

            overview_capture = _capture(page, ASSEMBLY, overview["pageId"])
            overview_png = OUT / "overview-hlr-source.png"
            overview_png.write_bytes(base64.b64decode(overview_capture["pngBase64"]))
            overview["renderRequest"]["image"] = overview_capture["artifact"]
            group_balloons = overview_capture["artifact"].get("balloons") or []
            group_items = overview.get("manualGroupItems") or []
            check(
                "test_4_group_anchor_contract_passes",
                len(group_balloons) == len(group_items) == 3
                and all(row.get("anchorScope") == "manual_group" for row in group_balloons)
                and all(row.get("calloutType") == "group" for row in group_balloons)
                and {
                    row.get("manualGroupId") for row in group_balloons
                } == {
                    row.get("sectionId") for row in group_items
                },
                {
                    "groupItemCount": len(group_items),
                    "balloonCount": len(group_balloons),
                    "anchorScopes": [row.get("anchorScope") for row in group_balloons],
                    "groupIds": [row.get("manualGroupId") for row in group_balloons],
                },
            )
            _overview_sample(
                document,
                overview,
                overview_png,
                OUT / "test-04b-complete-assembly-group-anchors.png",
            )
            context.close()
            browser.close()
    finally:
        server.stop()
        (OUT / "technical_samples_report.json").write_text(
            json.dumps(report, indent=2, sort_keys=True),
            encoding="utf-8",
        )

    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(run())
