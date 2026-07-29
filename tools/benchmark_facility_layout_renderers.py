#!/usr/bin/env python3
"""Run the deterministic Facility Layout top-plan renderer benchmark."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = ROOT / "tests" / "fixtures" / "facility_layout" / "rendering"
BENCHMARK_HTML = FIXTURE_DIR / "renderer-benchmark.html"
SPEC_PATH = FIXTURE_DIR / "renderer-benchmark-spec.json"
DEFAULT_OUTPUT = FIXTURE_DIR / "renderer-benchmark-results.json"
DEFAULT_EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
RENDERERS = ("svg", "canvas2d", "webgl")
SCENARIOS = ("edit-500", "navigate-5000")


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_value(*args: str) -> str | None:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout.strip()


def percentile(samples: list[float], quantile: float) -> float | None:
    if not samples:
        return None
    ordered = sorted(samples)
    position = (len(ordered) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 4)


def summarize(entries: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for renderer in RENDERERS:
        summary[renderer] = {}
        for scenario in SCENARIOS:
            selected = [
                entry
                for entry in entries
                if entry["renderer"] == renderer and entry["scenario"] == scenario
            ]
            if not selected:
                continue
            frame_samples = [
                float(sample)
                for entry in selected
                for sample in entry["measurement"]["frameIntervalsMs"]
            ]
            callback_samples = [
                float(sample)
                for entry in selected
                for sample in entry["measurement"]["callbackMs"]
            ]
            build_samples = [float(entry["setup"]["buildSyncMs"]) for entry in selected]
            paint_samples = [
                float(entry["setup"]["firstPaintReadyMs"]) for entry in selected
            ]
            long_tasks = [
                task
                for entry in selected
                for task in entry["measurement"]["longTasks"]
            ]
            total_wall_ms = sum(
                float(entry["measurement"]["wallDurationMs"]) for entry in selected
            )
            heap_deltas = []
            for entry in selected:
                before = entry["measurement"].get("heapBefore")
                after = entry["measurement"].get("heapAfter")
                if before and after:
                    heap_deltas.append(
                        int(after["usedJSHeapSize"]) - int(before["usedJSHeapSize"])
                    )

            summary[renderer][scenario] = {
                "runCount": len(selected),
                "frameSampleCount": len(frame_samples),
                "effectiveFps": rounded(
                    (len(frame_samples) * 1000 / total_wall_ms)
                    if total_wall_ms
                    else None
                ),
                "frameIntervalMs": {
                    "median": rounded(percentile(frame_samples, 0.5)),
                    "p95": rounded(percentile(frame_samples, 0.95)),
                    "p99": rounded(percentile(frame_samples, 0.99)),
                    "max": rounded(max(frame_samples) if frame_samples else None),
                },
                "callbackMs": {
                    "median": rounded(percentile(callback_samples, 0.5)),
                    "p95": rounded(percentile(callback_samples, 0.95)),
                    "p99": rounded(percentile(callback_samples, 0.99)),
                    "max": rounded(max(callback_samples) if callback_samples else None),
                },
                "framesOver22Ms": sum(sample > 22 for sample in frame_samples),
                "framesOver33Ms": sum(sample > 33 for sample in frame_samples),
                "buildSyncMs": {
                    "median": rounded(percentile(build_samples, 0.5)),
                    "p95": rounded(percentile(build_samples, 0.95)),
                },
                "firstPaintReadyMs": {
                    "median": rounded(percentile(paint_samples, 0.5)),
                    "p95": rounded(percentile(paint_samples, 0.95)),
                },
                "longTaskCount": len(long_tasks),
                "maxLongTaskMs": rounded(
                    max(
                        (float(task["durationMs"]) for task in long_tasks),
                        default=0.0,
                    )
                ),
                "usedHeapDeltaBytes": {
                    "median": rounded(percentile(heap_deltas, 0.5)),
                    "max": max(heap_deltas, default=0),
                },
                "rendererMetrics": selected[0]["measurement"]["rendererMetrics"],
                "placementHashSha256": selected[0]["setup"][
                    "placementHashSha256"
                ],
            }
    return summary


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark SVG, Canvas 2D, and instanced WebGL against deterministic "
            "500-placement editing and 5,000-placement navigation workloads."
        )
    )
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--warmup-seconds", type=float, default=10.0)
    parser.add_argument("--duration-seconds", type=float, default=60.0)
    parser.add_argument(
        "--renderers",
        nargs="+",
        choices=RENDERERS,
        default=list(RENDERERS),
    )
    parser.add_argument(
        "--scenarios",
        nargs="+",
        choices=SCENARIOS,
        default=list(SCENARIOS),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--edge-path", type=Path, default=DEFAULT_EDGE)
    parser.add_argument("--headed", action="store_true")
    parser.add_argument(
        "--smoke",
        action="store_true",
        help="Run one 0.5-second sample per selected renderer/scenario.",
    )
    args = parser.parse_args()
    if args.smoke:
        args.runs = 1
        args.warmup_seconds = 0.1
        args.duration_seconds = 0.5
    if args.runs < 1:
        parser.error("--runs must be at least 1")
    if args.warmup_seconds < 0 or args.duration_seconds <= 0:
        parser.error("durations must be positive (warm-up may be zero)")
    return args


def main() -> int:
    args = parse_args()
    for required in (BENCHMARK_HTML, SPEC_PATH):
        if not required.is_file():
            raise SystemExit(f"Missing benchmark input: {required}")
    if not args.edge_path.is_file():
        raise SystemExit(f"Microsoft Edge not found: {args.edge_path}")

    handler = partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    benchmark_url = (
        f"{origin}/tests/fixtures/facility_layout/rendering/"
        "renderer-benchmark.html"
    )
    entries: list[dict[str, Any]] = []
    run_errors: list[dict[str, Any]] = []
    started_at = time.time()

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(args.edge_path),
                headless=not args.headed,
                args=[
                    "--enable-precise-memory-info",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows",
                ],
            )
            context = browser.new_context(
                viewport={"width": 1440, "height": 960},
                device_scale_factor=1,
            )
            blocked_requests: list[str] = []

            def route_request(route: Any) -> None:
                if route.request.url.startswith(origin):
                    route.continue_()
                else:
                    blocked_requests.append(route.request.url)
                    route.abort()

            context.route("**/*", route_request)
            browser_version = browser.version
            total = args.runs * len(args.renderers) * len(args.scenarios)
            completed = 0

            for run_index in range(args.runs):
                renderer_order = list(args.renderers)
                shift = run_index % len(renderer_order)
                renderer_order = renderer_order[shift:] + renderer_order[:shift]
                for scenario in args.scenarios:
                    for renderer in renderer_order:
                        completed += 1
                        page = context.new_page()
                        page_errors: list[str] = []
                        console_errors: list[str] = []
                        page.on("pageerror", lambda error: page_errors.append(str(error)))
                        page.on(
                            "console",
                            lambda message: (
                                console_errors.append(message.text)
                                if message.type == "error"
                                else None
                            ),
                        )
                        print(
                            f"[{completed}/{total}] run={run_index + 1} "
                            f"renderer={renderer} scenario={scenario}",
                            flush=True,
                        )
                        try:
                            page.goto(benchmark_url, wait_until="load", timeout=30_000)
                            page.wait_for_function(
                                """() => {
                                    const api = window.facilityLayoutRendererBenchmark;
                                    return Boolean(api && api.spec);
                                }""",
                                timeout=30_000,
                            )
                            setup = page.evaluate(
                                """options =>
                                    window.facilityLayoutRendererBenchmark.setup(options)""",
                                {"renderer": renderer, "scenario": scenario},
                            )
                            measurement = page.evaluate(
                                """options =>
                                    window.facilityLayoutRendererBenchmark.run(options)""",
                                {
                                    "warmupMs": args.warmup_seconds * 1000,
                                    "durationMs": args.duration_seconds * 1000,
                                },
                            )
                            entries.append(
                                {
                                    "runIndex": run_index,
                                    "renderer": renderer,
                                    "scenario": scenario,
                                    "setup": setup,
                                    "measurement": measurement,
                                    "pageErrors": page_errors,
                                    "consoleErrors": console_errors,
                                }
                            )
                        except PlaywrightError as error:
                            run_errors.append(
                                {
                                    "runIndex": run_index,
                                    "renderer": renderer,
                                    "scenario": scenario,
                                    "error": str(error),
                                    "pageErrors": page_errors,
                                    "consoleErrors": console_errors,
                                }
                            )
                        finally:
                            page.close()

            runtime = entries[0]["measurement"]["runtime"] if entries else None
            context.close()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        server_thread.join(timeout=5)

    tracked_status = git_value("status", "--porcelain", "--untracked-files=no")
    result = {
        "schemaVersion": "facility-layout-renderer-benchmark-results-v1",
        "benchmarkScope": (
            "Top-plan placement footprints only; excludes zones, routes, labels, "
            "clearances, picking, spatial queries, 3D, loading, context loss, and remount."
        ),
        "protocol": {
            "runs": args.runs,
            "warmupSecondsPerRun": args.warmup_seconds,
            "measuredSecondsPerRun": args.duration_seconds,
            "headless": not args.headed,
            "renderers": args.renderers,
            "scenarios": args.scenarios,
            "rendererOrderRotatedByRun": True,
            "externalRequestsBlocked": True,
        },
        "environment": {
            "capturedAtUtc": time.strftime(
                "%Y-%m-%dT%H:%M:%SZ", time.gmtime(started_at)
            ),
            "elapsedSeconds": round(time.time() - started_at, 3),
            "os": platform.platform(),
            "python": sys.version,
            "playwright": "1.56.0",
            "browser": f"Microsoft Edge {browser_version}",
            "edgeExecutable": str(args.edge_path),
            "runtime": runtime,
        },
        "source": {
            "gitCommit": git_value("rev-parse", "HEAD"),
            "trackedWorktreeDirty": bool(tracked_status),
            "specSha256": sha256_file(SPEC_PATH),
            "benchmarkHtmlSha256": sha256_file(BENCHMARK_HTML),
            "runnerSha256": sha256_file(Path(__file__).resolve()),
        },
        "network": {
            "servedOrigin": origin,
            "blockedExternalRequests": blocked_requests,
        },
        "summary": summarize(entries),
        "runs": entries,
        "errors": run_errors,
    }
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output}", flush=True)
    print(
        f"Completed {len(entries)} samples with {len(run_errors)} errors.",
        flush=True,
    )
    return 2 if run_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
