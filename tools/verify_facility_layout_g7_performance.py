"""Qualify G7 generation latency, memory growth, and repeated cleanup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
from typing import Any
from urllib.request import urlopen
import uuid

import psutil
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ai_inspector.facility_layout.knowledge_foundation import (
    canonical_facility_knowledge_bytes,
)
from verify_facility_layout_g2_circulation import _open_facility
from verify_facility_layout_g7_parity import PROGRAM
from verify_facility_layout_p11 import (
    build_real_soak_evidence,
    run_accelerated_soak,
)


EVIDENCE_ROOT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "production_hardening"
)
DEFAULT_OUTPUT = EVIDENCE_ROOT / "fli031-performance-evidence.json"
DEFAULT_SOAK_OUTPUT = EVIDENCE_ROOT / "fli031-accelerated-soak.json"
DEFAULT_REAL_SOAK_LEDGER = (
    ROOT / ".runtime" / "facility_layout" / "g7-real-soak-events.json"
)
SOURCE_PATHS = (
    "ai_inspector/facility_layout/generation_coordinator.py",
    "ai_inspector/facility_layout/generation_run_repository.py",
    "ai_inspector/facility_layout/full_factory.py",
    "ai_inspector/facility_layout/soak_evidence.py",
    "static/index.html",
    "static/facility_layout_session.js",
    "static/facility_layout_three_adapter.js",
    "static/facility_layout_transport.js",
    "static/facility_layout_workspace.js",
    "tools/verify_facility_layout_g7_performance.py",
    "tools/verify_facility_layout_p11.py",
    "tools/record_facility_layout_soak.py",
)
MEASURED_CYCLES = 20
BUDGETS = {
    "fullFactoryGenerationP95Ms": 6000.0,
    "generationTransitionP95Ms": 1500.0,
    "undoP95Ms": 1000.0,
    "javascriptHeapGrowthPercent": 10.0,
    "browserRssEndGrowthBytes": 256 * 1024 * 1024,
    "browserRssPeakGrowthBytes": 512 * 1024 * 1024,
    "serverRssEndGrowthBytes": 128 * 1024 * 1024,
    "serverRssPeakGrowthBytes": 256 * 1024 * 1024,
    "maximumPendingLoadsAfterFit": 0,
    "maximumCanvasCountAfterCleanup": 1,
    "maximumActiveRenderRequestsAfterCleanup": 0,
}


def _revision(value: Any) -> str:
    return hashlib.sha256(canonical_facility_knowledge_bytes(value)).hexdigest()


def _source_binding() -> dict[str, Any]:
    records = []
    for relative in SOURCE_PATHS:
        path = ROOT / relative
        records.append(
            {
                "path": relative,
                "byteLength": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        )
    return {"files": records, "aggregateSha256": _revision(records)}


def _p95(values: list[float]) -> float:
    if not values:
        return 0.0
    return float(
        statistics.quantiles(values, n=100, method="inclusive")[94]
        if len(values) > 1
        else values[0]
    )


def _process_rss(process_id: int | None) -> int | None:
    if process_id is None:
        return None
    try:
        return int(psutil.Process(process_id).memory_info().rss)
    except (psutil.Error, OSError):
        return None


def _browser_rss(cdp_session: Any) -> dict[str, Any]:
    response = cdp_session.send("SystemInfo.getProcessInfo")
    records = []
    total = 0
    for item in response.get("processInfo", []):
        process_id = int(item.get("id") or 0)
        rss = _process_rss(process_id)
        if rss is None:
            continue
        records.append(
            {
                "processId": process_id,
                "type": str(item.get("type") or "unknown"),
                "rssBytes": rss,
            }
        )
        total += rss
    return {"rssBytes": total, "processes": records}


def _bootstrap(app_url: str) -> dict[str, Any]:
    with urlopen(
        app_url.rstrip("/") + "/api/facility-layout-bootstrap", timeout=30
    ) as response:
        return json.loads(response.read().decode("utf-8"))


def _collect_environment(page: Any, browser: Any) -> dict[str, Any]:
    browser_values = page.evaluate(
        """() => {
            const canvas = document.createElement('canvas');
            const gl = canvas.getContext('webgl2') || canvas.getContext('webgl');
            const extension = gl && gl.getExtension('WEBGL_debug_renderer_info');
            return {
                userAgent: navigator.userAgent,
                hardwareConcurrency: navigator.hardwareConcurrency,
                deviceMemoryGiB: navigator.deviceMemory || null,
                platform: navigator.platform,
                preciseMemoryInfo: performance.memory ? {
                    jsHeapSizeLimit: performance.memory.jsHeapSizeLimit,
                    totalJSHeapSize: performance.memory.totalJSHeapSize,
                    usedJSHeapSize: performance.memory.usedJSHeapSize,
                } : null,
                webgl: gl ? {
                    version: gl.getParameter(gl.VERSION),
                    renderer: extension
                        ? gl.getParameter(extension.UNMASKED_RENDERER_WEBGL)
                        : gl.getParameter(gl.RENDERER),
                    vendor: extension
                        ? gl.getParameter(extension.UNMASKED_VENDOR_WEBGL)
                        : gl.getParameter(gl.VENDOR),
                } : null,
            };
        }"""
    )
    memory = psutil.virtual_memory()
    return {
        "operatingSystem": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
        },
        "machine": {
            "hostname": platform.node(),
            "processor": platform.processor(),
            "architecture": platform.machine(),
            "logicalCpuCount": psutil.cpu_count(logical=True),
            "physicalCpuCount": psutil.cpu_count(logical=False),
            "physicalMemoryBytes": int(memory.total),
        },
        "python": sys.version,
        "playwrightBrowserVersion": browser.version,
        "browser": browser_values,
    }


def _run_cycle(page: Any) -> dict[str, Any]:
    return page.evaluate(
        """async program => {
            const app = window._trainFacilityLayoutAuthoringApp;
            const now = () => performance.now();
            const callDurations = [];
            let state = app.session.getState();
            if (state.generatedDraft) await app.session.undo();
            if (state.dirty) app.session.discard();
            const startedAt = now();
            let callStarted = now();
            let run = await app.transport.startFullFactoryGeneration({
                prototypeMode: true,
                supersedeActiveDraft: true,
                workspaceId: 'workspace-facility-layout',
                fullFactory: program,
            });
            callDurations.push(now() - callStarted);
            let transitions = 0;
            while (run.currentStageId && transitions < 128) {
                callStarted = now();
                run = await app.transport.continueGenerationRun({
                    runId: run.runId,
                    explicitStageAcceptance: false,
                });
                callDurations.push(now() - callStarted);
                transitions += 1;
                if (run.draftLayout) app.session.installGenerationDraft(run);
            }
            const generationMs = now() - startedAt;
            app.workspace._setViewMode('3d');
            await app.workspace.executeCommand('fit');
            const loadStarted = now();
            while (now() - loadStarted < 30000) {
                const diagnostics = app.workspace.threeAdapter.getDiagnostics();
                if (diagnostics.pendingLoads === 0) break;
                await new Promise(resolve => setTimeout(resolve, 25));
            }
            await app.workspace.whenIdle();
            const three = app.workspace.threeAdapter.getDiagnostics();
            app.workspace._setViewMode('plan');
            await app.workspace.executeCommand('fit');
            await app.workspace.whenIdle();
            const undoStarted = now();
            await app.session.undo();
            await app.workspace.whenIdle();
            const undoMs = now() - undoStarted;
            if (typeof window.gc === 'function') window.gc();
            await new Promise(resolve => setTimeout(resolve, 150));
            const after = app.session.getState();
            const cleanup = app.workspace.threeAdapter.getDiagnostics();
            return {
                runId: run.runId,
                status: run.status,
                transitions,
                receiptCount: Array.isArray(run.receiptChain)
                    ? run.receiptChain.length : 0,
                generationMs,
                transitionCallDurationsMs: callDurations,
                undoMs,
                draftCounts: {
                    zones: (run.draftLayout.zones || []).length,
                    routes: (run.draftLayout.routes || []).length,
                    floorMarkings: (run.draftLayout.floorMarkings || []).length,
                    placements: (run.draftLayout.placements || []).length,
                },
                threeAtFit: {
                    status: three.status,
                    pendingLoads: three.pendingLoads,
                    placementAuditStatus:
                        three.placementTransformAudit.status,
                    placementCount: three.placementCount,
                    routeCount: three.routeCount,
                    floorMarkingCount: three.floorMarkingCount,
                },
                cleanup: {
                    dirty: after.dirty,
                    generatedDraft: after.generatedDraft,
                    layoutEqualsBase:
                        JSON.stringify(after.layout)
                        === JSON.stringify(after.baseLayout),
                    canvasCount: cleanup.lifecycle.canvasCount,
                    pendingFrame: cleanup.demandRendering.pendingFrame,
                    activeRenderRequests:
                        cleanup.demandRendering.pendingFrame ? 1 : 0,
                    pendingLoads: cleanup.pendingLoads,
                },
                jsHeap: performance.memory ? {
                    usedJSHeapSize: performance.memory.usedJSHeapSize,
                    totalJSHeapSize: performance.memory.totalJSHeapSize,
                    jsHeapSizeLimit: performance.memory.jsHeapSizeLimit,
                } : null,
            };
        }""",
        PROGRAM,
    )


def verify(
    app_url: str,
    output: Path,
    soak_output: Path,
    real_soak_ledger: Path,
    server_pid: int | None,
) -> dict[str, Any]:
    output.parent.mkdir(parents=True, exist_ok=True)
    soak_output.parent.mkdir(parents=True, exist_ok=True)
    source_before = _source_binding()
    saved_before = _bootstrap(app_url)["layout"]
    if any(
        saved_before["layout"].get(key)
        for key in ("zones", "routes", "floorMarkings", "placements")
    ):
        raise RuntimeError("G7 performance proof requires the saved blank baseline.")
    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_responses: list[dict[str, Any]] = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--enable-precise-memory-info",
                "--js-flags=--expose-gc",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
            ],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            device_scale_factor=1,
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: (
                console_errors.append(message.text)
                if message.type == "error"
                else None
            ),
        )

        def observe(response: Any) -> None:
            if response.status >= 400 and not response.url.endswith(
                "/static/manifest.json"
            ):
                failed_responses.append(
                    {
                        "method": response.request.method,
                        "status": response.status,
                        "url": response.url,
                    }
                )

        page.on("response", observe)
        page.goto(app_url, wait_until="load", timeout=120_000)
        _open_facility(page)
        environment = _collect_environment(page, browser)
        cdp_session = browser.new_browser_cdp_session()

        warmup = _run_cycle(page)
        if warmup["status"] != "complete":
            raise RuntimeError(f"G7 warmup did not complete: {warmup}")
        browser_baseline = _browser_rss(cdp_session)
        server_baseline = _process_rss(server_pid)
        heap_baseline = warmup["jsHeap"]
        cycles = []
        browser_samples = [browser_baseline["rssBytes"]]
        server_samples = [server_baseline] if server_baseline is not None else []
        for index in range(MEASURED_CYCLES):
            cycle = _run_cycle(page)
            cycle["sequence"] = index + 1
            cycle["browserRssBytes"] = _browser_rss(cdp_session)["rssBytes"]
            cycle["serverRssBytes"] = _process_rss(server_pid)
            browser_samples.append(cycle["browserRssBytes"])
            if cycle["serverRssBytes"] is not None:
                server_samples.append(cycle["serverRssBytes"])
            cycles.append(cycle)
        browser_final = _browser_rss(cdp_session)
        server_final = _process_rss(server_pid)
        context.close()
        browser.close()

    generation_samples = [float(item["generationMs"]) for item in cycles]
    transition_samples = [
        float(value)
        for item in cycles
        for value in item["transitionCallDurationsMs"]
    ]
    undo_samples = [float(item["undoMs"]) for item in cycles]
    heap_final = cycles[-1]["jsHeap"]
    heap_samples = [
        int(item["jsHeap"]["usedJSHeapSize"])
        for item in cycles
    ]
    heap_window_size = min(5, len(heap_samples))
    heap_first_window_median = statistics.median(
        heap_samples[:heap_window_size]
    )
    heap_last_window_median = statistics.median(
        heap_samples[-heap_window_size:]
    )
    heap_growth_percent = (
        100.0
        * (heap_last_window_median - heap_first_window_median)
        / max(1, heap_first_window_median)
    )
    heap_endpoint_growth_percent = (
        100.0
        * (heap_final["usedJSHeapSize"] - heap_baseline["usedJSHeapSize"])
        / max(1, heap_baseline["usedJSHeapSize"])
    )
    browser_end_growth = (
        browser_final["rssBytes"] - browser_baseline["rssBytes"]
    )
    browser_peak_growth = max(browser_samples) - browser_baseline["rssBytes"]
    server_end_growth = (
        None
        if server_baseline is None or server_final is None
        else server_final - server_baseline
    )
    server_peak_growth = (
        None
        if server_baseline is None or not server_samples
        else max(server_samples) - server_baseline
    )
    observed = {
        "fullFactoryGenerationP95Ms": round(_p95(generation_samples), 6),
        "generationTransitionP95Ms": round(_p95(transition_samples), 6),
        "undoP95Ms": round(_p95(undo_samples), 6),
        "javascriptHeapGrowthPercent": round(heap_growth_percent, 6),
        "javascriptHeapEndpointGrowthPercent": round(
            heap_endpoint_growth_percent,
            6,
        ),
        "javascriptHeapFirstWindowMedianBytes": heap_first_window_median,
        "javascriptHeapLastWindowMedianBytes": heap_last_window_median,
        "browserRssEndGrowthBytes": browser_end_growth,
        "browserRssPeakGrowthBytes": browser_peak_growth,
        "serverRssEndGrowthBytes": server_end_growth,
        "serverRssPeakGrowthBytes": server_peak_growth,
        "maximumPendingLoadsAfterFit": max(
            int(item["threeAtFit"]["pendingLoads"]) for item in cycles
        ),
        "maximumCanvasCountAfterCleanup": max(
            int(item["cleanup"]["canvasCount"]) for item in cycles
        ),
        "maximumActiveRenderRequestsAfterCleanup": max(
            int(item["cleanup"]["activeRenderRequests"]) for item in cycles
        ),
    }
    budget_checks = {
        key: observed[key] is not None and float(observed[key]) <= float(limit)
        for key, limit in BUDGETS.items()
    }
    cycle_checks = {
        "allRunsComplete": all(item["status"] == "complete" for item in cycles),
        "allRunsUseTenStages": all(
            item["transitions"] == 10 and item["receiptCount"] == 10
            for item in cycles
        ),
        "allDraftCountsExact": all(
            item["draftCounts"]
            == {"zones": 12, "routes": 2, "floorMarkings": 1, "placements": 6}
            for item in cycles
        ),
        "allThreeRepresentationsMatch": all(
            item["threeAtFit"]["status"] == "ready"
            and item["threeAtFit"]["placementAuditStatus"] == "match"
            and item["threeAtFit"]["placementCount"] == 6
            and item["threeAtFit"]["routeCount"] == 2
            and item["threeAtFit"]["floorMarkingCount"] == 1
            for item in cycles
        ),
        "allUndoCleanupExact": all(
            item["cleanup"]["dirty"] is False
            and item["cleanup"]["generatedDraft"] is None
            and item["cleanup"]["layoutEqualsBase"] is True
            and item["cleanup"]["pendingFrame"] is False
            and item["cleanup"]["pendingLoads"] == 0
            for item in cycles
        ),
    }

    accelerated_root = (
        ROOT
        / ".runtime"
        / "facility_layout"
        / f"g7-accelerated-soak-{uuid.uuid4().hex}"
    )
    real_soak = build_real_soak_evidence(real_soak_ledger)
    accelerated = run_accelerated_soak(
        accelerated_root,
        real_soak_evidence=real_soak,
    )
    soak_output.write_text(
        json.dumps(accelerated, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    saved_after = _bootstrap(app_url)["layout"]
    source_after = _source_binding()
    qualification_checks = {
        "allNumericBudgetsPassed": all(budget_checks.values()),
        "allCycleContractsPassed": all(cycle_checks.values()),
        "acceleratedSoakPassed": (
            accelerated["acceleratedDeterministicSoak"]["status"] == "passed"
            and all(
                accelerated["acceleratedDeterministicSoak"]["checks"].values()
            )
        ),
        "savedLayoutUnchanged": saved_after == saved_before,
        "sourceStableDuringQualification": source_before == source_after,
        "preciseHeapAvailable": heap_baseline is not None and heap_final is not None,
        "serverRssAvailable": server_baseline is not None and server_final is not None,
        "noPageErrors": not page_errors,
        "noConsoleErrors": not console_errors,
        "noFailedResponses": not failed_responses,
    }
    controlled_release_blockers = list(real_soak.get("blockers") or [])
    if real_soak.get("releaseGateMet") is not True:
        controlled_release_blockers.append(
            "literal_fourteen_day_elapsed_soak_not_completed"
        )
    controlled_release_blockers = sorted(set(controlled_release_blockers))
    evidence = {
        "schemaVersion": "facility-layout-fli031-performance-v1",
        "passed": all(qualification_checks.values()),
        "controlledReleaseGateMet": accelerated["releaseGateMet"] is True,
        "controlledReleaseBlockers": controlled_release_blockers,
        "checks": qualification_checks,
        "budgets": BUDGETS,
        "observed": observed,
        "budgetChecks": budget_checks,
        "cycleChecks": cycle_checks,
        "protocol": {
            "discardedWarmupCycles": 1,
            "measuredCycles": MEASURED_CYCLES,
            "cycleWorkload": (
                "full_factory_generation_then_3d_fit_then_plan_then_exact_undo"
            ),
            "percentileMethod": "inclusive",
            "javascriptCollection": "performance.memory_after_exposed_gc",
            "javascriptGrowthComparison": (
                "median_of_first_and_last_five_post_gc_measured_cycles"
            ),
            "javascriptGrowthWindowSize": heap_window_size,
            "rssCollection": "psutil_process_rss",
        },
        "environment": environment,
        "serverProcessId": server_pid,
        "sourceBinding": source_before,
        "baseRevision": saved_before["revision"],
        "memory": {
            "heapBaseline": heap_baseline,
            "heapFinal": heap_final,
            "browserBaseline": browser_baseline,
            "browserFinal": browser_final,
            "serverBaselineRssBytes": server_baseline,
            "serverFinalRssBytes": server_final,
        },
        "samples": {
            "warmup": warmup,
            "cycles": cycles,
        },
        "acceleratedSoakArtifact": soak_output.relative_to(ROOT).as_posix(),
        "acceleratedSoakRuntimeRoot": accelerated_root.relative_to(ROOT).as_posix(),
        "realSoakLedger": real_soak_ledger.relative_to(ROOT).as_posix(),
        "errors": {
            "page": page_errors,
            "console": console_errors,
            "responses": failed_responses,
        },
    }
    output.write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
        newline="\n",
    )
    return evidence


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8141/")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--soak-output", type=Path, default=DEFAULT_SOAK_OUTPUT)
    parser.add_argument(
        "--real-soak-ledger",
        type=Path,
        default=DEFAULT_REAL_SOAK_LEDGER,
    )
    parser.add_argument("--server-pid", type=int)
    args = parser.parse_args()
    evidence = verify(
        args.url,
        args.output.resolve(),
        args.soak_output.resolve(),
        args.real_soak_ledger.resolve(),
        args.server_pid,
    )
    print(json.dumps({
        "passed": evidence["passed"],
        "observed": evidence["observed"],
        "budgetChecks": evidence["budgetChecks"],
        "checks": evidence["checks"],
        "controlledReleaseGateMet": evidence["controlledReleaseGateMet"],
        "controlledReleaseBlockers": evidence["controlledReleaseBlockers"],
    }, indent=2, sort_keys=True))
    return 0 if evidence["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
