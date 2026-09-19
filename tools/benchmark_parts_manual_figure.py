"""Benchmark and diagnose one live parts-manual technical figure.

This tool exercises the same browser capture and server validation used by the
application. It does not repair or bypass the product; it records enough
geometry, routing, visibility, and timing evidence to explain a failed figure.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import time

from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-") or "figure"


def run(
    *,
    base_url: str,
    assembly: str,
    figure: str,
    minimum_occurrences: int,
    output_dir: Path,
) -> int:
    output_dir.mkdir(parents=True, exist_ok=True)
    report: dict[str, object] = {
        "assembly": assembly,
        "figure": figure,
        "baseUrl": base_url,
    }
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
        page = browser.new_page(viewport={"width": 1720, "height": 1080})
        page.set_default_timeout(900_000)
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
                && Object.keys(
                    window.__compareDbg.state.assyOccurrenceMeshMap || {}
                ).length >= minimum
            )""",
            arg={"assembly": assembly, "minimum": minimum_occurrences},
            timeout=600_000,
        )
        page.evaluate(
            """async () => {
                window.__compareDbg.openDocumentationWorkflow();
                await _partsManualWaitForDocumentationWorkspace();
                const assemblyNumber = assemblyContext?.assembly_number;
                const payload = await _partsManualApi(
                    `/api/parts-manual/${encodeURIComponent(assemblyNumber)}`
                );
                if (!_documentationPlanIsReady(payload)) {
                    throw new Error('The parts-manual plan is not ready for a figure benchmark.');
                }
                window.__compareDbg.state.partsManualPayload = payload;
                const scenePayload = await _partsManualApi(
                    `/api/parts-manual/${encodeURIComponent(assemblyNumber)}`
                    + '/documentation-scene'
                );
                _documentationUpdatePayload(scenePayload, { revealAll: true });
            }"""
        )
        page.wait_for_function(
            """() => Boolean(
                window.__compareDbg.state.partsManualDocumentation?.document?.pages?.length
                && document.getElementById('documentationPublicationSurface')
            )""",
            timeout=300_000,
        )
        result = page.evaluate(
            """async figureNumber => {
                const payload = window.__compareDbg.state.partsManualPayload;
                const documentPayload = window.__compareDbg.state.partsManualDocumentation;
                const targetPage = documentPayload.document.pages.find(
                    row => row.figureNumber === figureNumber
                );
                if (!payload || !targetPage) {
                    throw new Error(`Figure ${figureNumber} is unavailable.`);
                }
                await _documentationActivatePage(
                    targetPage.pageId,
                    null,
                    { busy: false, status: false }
                );
                window.__compareDbg.state.partsManualDocumentationLiveEditPageId =
                    targetPage.pageId;
                _documentationRenderPublicationPage(targetPage);
                const startedAt = performance.now();
                _partsManualViewDocumentPage(payload, targetPage);
                await _partsManualWaitForRenderPose();
                const poseReadyAt = performance.now();
                const pageMeshes = _partsManualPageMeshes(targetPage)
                    .filter(mesh => mesh?.isMesh && mesh.visible);
                const camera = window.__compareDbg.state.assyCamera;
                const visibilityContext = _partsManualCalloutVisibilityContext(
                    pageMeshes,
                    camera
                );
                const geometryDiagnostics = (targetPage.bom || []).map(item => {
                    const occurrenceRows = (item.occurrenceIds || []).map(occurrenceId => {
                        const meshes = (
                            window.__compareDbg.state.assyOccurrenceMeshMap?.[occurrenceId]
                            || []
                        ).filter(mesh => mesh?.isMesh && mesh.visible);
                        const bounds = _partsManualProjectedBounds(meshes, camera);
                        const worldBox = _partsManualBoxForMeshes(meshes);
                        const worldCenter = worldBox.getCenter(new THREE.Vector3());
                        const worldSize = worldBox.getSize(new THREE.Vector3());
                        const samples = bounds
                            ? _partsManualVisibleAnchorSamples(
                                meshes,
                                bounds,
                                camera,
                                pageMeshes,
                                occurrenceId,
                                visibilityContext
                            )
                            : [];
                        return {
                            occurrenceId,
                            meshCount: meshes.length,
                            triangleCount: meshes.reduce((total, mesh) => {
                                const geometry = mesh.geometry;
                                return total + Math.floor(
                                    geometry?.index?.count
                                        ? geometry.index.count / 3
                                        : (geometry?.attributes?.position?.count || 0) / 3
                                );
                            }, 0),
                            worldCenter: worldCenter.toArray(),
                            worldSize: worldSize.toArray(),
                            bounds,
                            visibleSampleCount: samples.length,
                            samplingDivisions: Number(samples[0]?.samplingDivisions || 0),
                            samplingProbeCount: Number(samples[0]?.samplingProbeCount || 0),
                        };
                    });
                    return {
                        item: item.item,
                        definitionId: item.definitionId,
                        description: item.description,
                        quantity: item.quantity,
                        occurrences: occurrenceRows,
                    };
                });

                let captureReceipt = null;
                let captureError = null;
                let serverArtifact = null;
                try {
                    captureReceipt = await _partsManualCapturePageWithRetries(
                        payload,
                        documentPayload.document,
                        targetPage
                    );
                    serverArtifact = captureReceipt?.artifact || null;
                } catch (error) {
                    captureError = String(error?.message || error);
                }
                const capturedAt = performance.now();
                const routeQa = window.__compareDbg.state.partsManualRouteQaDiagnostics || {};
                const calloutQuality = serverArtifact?.quality?.calloutQuality || {};
                return {
                    pageId: targetPage.pageId,
                    title: targetPage.title,
                    renderPipelineVersion:
                        documentPayload.document.renderPipelineVersion || null,
                    poseMs: poseReadyAt - startedAt,
                    captureMs: capturedAt - poseReadyAt,
                    totalMs: capturedAt - startedAt,
                    pngBytes: Number(serverArtifact?.sizeBytes || 0),
                    balloonCount: Number(calloutQuality.balloonCount || 0),
                    captureAttempts: Number(captureReceipt?.attempt || 0),
                    captureFailures: captureReceipt?.failures || [],
                    captureError,
                    serverArtifact,
                    explodeVisibilityDiagnostics:
                        window.__compareDbg.state.partsManualExplodeVisibilityDiagnostics || [],
                    geometryDiagnostics,
                    hlrDiagnostics:
                        window.__compareDbg.state.partsManualHlrPassDiagnostics || null,
                    captureStages:
                        window.__compareDbg.state.partsManualCaptureDiagnostics || null,
                    routeDiagnostics: {
                        exactCandidateCount: routeQa.exactCandidateCount,
                        availableCandidateCount: routeQa.availableCandidateCount,
                        candidates: (routeQa.candidates || []).map(candidate => ({
                            strategy: candidate.strategy,
                            score: candidate.score,
                            presentationScore: candidate.presentationScore,
                            visualMetrics: candidate.visualMetrics || null,
                            invalidRows: (candidate.rows || []).filter(row =>
                                Number(row.geometryIntersectionCount || 0) > 0
                                || Number(row.leaderCrossingCount || 0) > 0
                                || Number(row.leaderBalloonCollisionCount || 0) > 0
                            ),
                        })),
                        repeated: (routeQa.repeated || []).map(row => ({
                            itemNumber: row.itemNumber,
                            calloutType: row.calloutType,
                            rejectedBranches:
                                row.diagnostics?.rejectedBranches?.length || 0,
                            missingOccurrences:
                                row.diagnostics?.missingOccurrenceIds?.length || 0,
                        })),
                    },
                };
            }""",
            figure,
        )
        report.update(result)
        page.screenshot(
            path=output_dir / f"figure-{_slug(figure)}-editor.png",
            full_page=True,
        )
        browser.close()

    (output_dir / "report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "assembly": report.get("assembly"),
                "figure": report.get("figure"),
                "title": report.get("title"),
                "renderPipelineVersion": report.get("renderPipelineVersion"),
                "captureAttempts": report.get("captureAttempts"),
                "captureFailures": report.get("captureFailures"),
                "captureError": report.get("captureError"),
                "serverStatus": (report.get("serverArtifact") or {}).get("status"),
                "calloutStatus": (
                    ((report.get("serverArtifact") or {}).get("quality") or {})
                    .get("calloutQuality") or {}
                ).get("status"),
                "totalMs": report.get("totalMs"),
                "report": str(output_dir / "report.json"),
            },
            indent=2,
        ),
        flush=True,
    )
    return 0 if not report.get("captureError") else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark one live parts-manual technical figure."
    )
    parser.add_argument("figure", nargs="?", default="3-1")
    parser.add_argument("--assembly", default="MMLE-50D")
    parser.add_argument("--base-url", default="http://127.0.0.1:8125")
    parser.add_argument("--minimum-occurrences", type=int, default=200)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output_dir = args.output_dir or (
        ROOT / ".runtime" / "parts_manual_figure_benchmark"
        / f"{_slug(args.assembly)}-{_slug(args.figure)}"
    )
    started = time.monotonic()
    code = run(
        base_url=args.base_url.rstrip("/"),
        assembly=args.assembly,
        figure=args.figure,
        minimum_occurrences=args.minimum_occurrences,
        output_dir=output_dir,
    )
    print(f"wallSeconds={time.monotonic() - started:.2f}", flush=True)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
