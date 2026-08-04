"""Benchmark the real Facility Layout workspace, plan, and Three adapters.

The release profile follows Section 18.3 of the Industrial Layout Platform
plan. The smoke profile exercises every measurement family with reduced counts
and is never eligible to claim the release gate.
"""

from __future__ import annotations

import argparse
import ctypes
import hashlib
import importlib.metadata
import json
import math
import os
import platform
import subprocess
import sys
import threading
import time
import uuid
from copy import deepcopy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, sync_playwright


ROOT = Path(__file__).resolve().parents[1]
PERFORMANCE_DIR = (
    ROOT / "tests" / "fixtures" / "facility_layout" / "performance"
)
BENCHMARK_HTML = (
    PERFORMANCE_DIR / "facility-layout-release-performance.html"
)
BENCHMARK_JS = (
    PERFORMANCE_DIR / "facility-layout-release-performance.js"
)
P4_LAYOUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "rendering"
    / "p4-facility-layout.json"
)
P4_CATALOG = P4_LAYOUT.with_name("p4-asset-catalog.json")
P5_HTML = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "authoring"
    / "p5-authoring.html"
)
P5_JS = P5_HTML.with_name("p5-authoring.js")
P5_RESULT = P5_HTML.with_name("p5-authoring-result.json")
BENCHMARK_MANIFEST = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "benchmark-fixture-manifest.json"
)
IMPLEMENTATION_PLAN = (
    ROOT / "docs" / "industrial-layout-platform-implementation-plan.md"
)
EDITOR = ROOT / "static" / "facility_layout_editor.js"
SESSION = ROOT / "static" / "facility_layout_session.js"
WORKSPACE = ROOT / "static" / "facility_layout_workspace.js"
WORKSPACE_CSS = ROOT / "static" / "facility_layout_workspace.css"
THREE_ADAPTER = ROOT / "static" / "facility_layout_three_adapter.js"
THREE_VENDOR = ROOT / "static" / "vendor" / "three" / "0.184.0"
THREE_MODULE = THREE_VENDOR / "build" / "three.module.min.js"
ORBIT_CONTROLS = THREE_VENDOR / "examples" / "jsm" / "controls" / "OrbitControls.js"
GLTF_LOADER = THREE_VENDOR / "examples" / "jsm" / "loaders" / "GLTFLoader.js"
RACK_OVERVIEW = (
    ROOT
    / "generated"
    / "industrial_assets"
    / "p0_spike"
    / "rack_prototypes"
    / "Pallet Racking_colored_overview_proxy.glb"
)
RACK_DETAIL = RACK_OVERVIEW.with_name("Pallet Racking_colored.glb")
DEFAULT_EDGE = Path(
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
)

RAW_SCHEMA = "facility-layout-browser-release-performance-raw-v1"
SUMMARY_SCHEMA = "facility-layout-browser-release-performance-summary-v1"
REQUIRED_PROGRESSIVE_STAGES = (
    "manifest",
    "footprint",
    "proxy",
    "overview",
    "detail",
)
NETWORK_PROFILES = {
    "local": {
        "latencyMs": 0,
        "downloadThroughputBytesPerSecond": -1,
        "uploadThroughputBytesPerSecond": -1,
        "connectionType": "wifi",
    },
    "50mbps": {
        "latencyMs": 0,
        "downloadThroughputBytesPerSecond": 6_250_000,
        "uploadThroughputBytesPerSecond": 6_250_000,
        "connectionType": "wifi",
    },
}


class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self, _format: str, *args: object) -> None:
        return


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(
        (
            json.dumps(value, ensure_ascii=True, indent=2, sort_keys=True)
            + "\n"
        ).encode("ascii")
    )


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
    return None if value is None else round(float(value), 4)


def latency_summary(samples: list[float]) -> dict[str, Any]:
    return {
        "sampleCount": len(samples),
        "medianMs": rounded(percentile(samples, 0.5)),
        "p95Ms": rounded(percentile(samples, 0.95)),
        "p99Ms": rounded(percentile(samples, 0.99)),
        "maximumMs": rounded(max(samples) if samples else None),
    }


def protocol_for(smoke: bool) -> dict[str, Any]:
    if smoke:
        return {
            "governingSection": "18.3",
            "profile": "smoke",
            "releaseEligible": False,
            "smoke": True,
            "discrete": {"discardedWarmups": 0, "measuredIterations": 1},
            "frame": {
                "runsPerScenario": 1,
                "warmupSecondsPerRun": 0.05,
                "measuredSecondsPerRun": 0.5,
                "minimumMeasuredFramesTotal": 1,
            },
            "assetLoading": {
                "discardedWarmupsPerCondition": 0,
                "measuredIterationsPerCondition": 1,
                "networkProfiles": ["local"],
                "cacheStates": ["cold"],
            },
            "remount": {
                "lifecycleMode": "bounded-suspend-resume",
                "discardedWarmupsPerSequence": 0,
                "independentSequences": 1,
                "cyclesPerSequence": 2,
                "freshBrowserContextPerSequence": True,
                "explicitInitialMountBeforeBaseline": True,
                "quiescenceMsBeforeMemorySample": 500,
            },
            "idleQuietWindowMs": 40,
        }
    return {
        "governingSection": "18.3",
        "profile": "release",
        "releaseEligible": True,
        "smoke": False,
        "discrete": {"discardedWarmups": 1, "measuredIterations": 30},
        "frame": {
            "runsPerScenario": 5,
            "warmupSecondsPerRun": 10.0,
            "measuredSecondsPerRun": 60.0,
            "minimumMeasuredFramesTotal": 3_000,
        },
        "assetLoading": {
            "discardedWarmupsPerCondition": 1,
            "measuredIterationsPerCondition": 30,
            "networkProfiles": ["local", "50mbps"],
            "cacheStates": ["cold", "warm"],
        },
        "remount": {
            # The release claim covers the first 20 remounts in each fresh
            # browser context. Hidden remount warmups would change that claim.
            "lifecycleMode": "bounded-suspend-resume",
            "discardedWarmupsPerSequence": 0,
            "independentSequences": 5,
            "cyclesPerSequence": 20,
            "freshBrowserContextPerSequence": True,
            "explicitInitialMountBeforeBaseline": True,
            "quiescenceMsBeforeMemorySample": 1_000,
        },
        "idleQuietWindowMs": 300,
    }


def source_specs() -> tuple[tuple[str, Path, str], ...]:
    return (
        ("benchmark_runner", Path(__file__).resolve(), "benchmark_runner"),
        ("benchmark_page", BENCHMARK_HTML, "benchmark_harness"),
        ("benchmark_script", BENCHMARK_JS, "benchmark_harness"),
        ("p4_layout", P4_LAYOUT, "authoritative_fixture"),
        ("p4_asset_catalog", P4_CATALOG, "authoritative_fixture"),
        ("p5_authoring_page", P5_HTML, "workspace_composition_reference"),
        ("p5_authoring_script", P5_JS, "workspace_composition_reference"),
        ("p5_authoring_result", P5_RESULT, "workspace_composition_reference"),
        ("facility_layout_editor", EDITOR, "production_adapter"),
        ("facility_layout_session", SESSION, "production_adapter"),
        ("facility_layout_workspace", WORKSPACE, "production_adapter"),
        ("facility_layout_workspace_css", WORKSPACE_CSS, "production_style"),
        ("facility_layout_three_adapter", THREE_ADAPTER, "production_adapter"),
        ("three_module", THREE_MODULE, "vendored_runtime"),
        ("orbit_controls", ORBIT_CONTROLS, "vendored_runtime"),
        ("gltf_loader", GLTF_LOADER, "vendored_runtime"),
        ("rack_overview_glb", RACK_OVERVIEW, "real_asset"),
        ("rack_detail_glb", RACK_DETAIL, "real_asset"),
        ("benchmark_fixture_manifest", BENCHMARK_MANIFEST, "governing_fixture"),
        ("implementation_plan", IMPLEMENTATION_PLAN, "governing_contract"),
    )


def source_records() -> list[dict[str, Any]]:
    return [
        {
            "sourceId": source_id,
            "path": path.relative_to(ROOT).as_posix(),
            "role": role,
            "byteLength": path.stat().st_size,
            "sha256": sha256_file(path),
        }
        for source_id, path, role in source_specs()
    ]


def _windows_physical_memory() -> int | None:
    if os.name != "nt":
        return None

    class MemoryStatusEx(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MemoryStatusEx()
    status.dwLength = ctypes.sizeof(MemoryStatusEx)
    if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None
    return int(status.ullTotalPhys)


def _display_size() -> dict[str, int | None]:
    if os.name == "nt":
        try:
            return {
                "width": int(ctypes.windll.user32.GetSystemMetrics(0)),
                "height": int(ctypes.windll.user32.GetSystemMetrics(1)),
            }
        except (AttributeError, OSError, ValueError):
            pass
    return {"width": None, "height": None}


def _windows_machine_identity() -> dict[str, Any] | None:
    if os.name != "nt":
        return None
    command = (
        "$cs=Get-CimInstance Win32_ComputerSystem;"
        "$cpus=@(Get-CimInstance Win32_Processor | ForEach-Object {"
        "[ordered]@{name=$_.Name;cores=$_.NumberOfCores;"
        "logicalProcessors=$_.NumberOfLogicalProcessors}});"
        "$gpus=@(Get-CimInstance Win32_VideoController | ForEach-Object {"
        "[ordered]@{name=$_.Name;adapterRam=$_.AdapterRAM;"
        "driverVersion=$_.DriverVersion}});"
        "[ordered]@{manufacturer=$cs.Manufacturer;model=$cs.Model;"
        "cpus=$cpus;gpus=$gpus}|ConvertTo-Json -Depth 5 -Compress"
    )
    for attempt in range(3):
        try:
            result = subprocess.run(
                [
                    "powershell.exe",
                    "-NoProfile",
                    "-NonInteractive",
                    "-Command",
                    command,
                ],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            value = json.loads(result.stdout)
        except (
            OSError,
            subprocess.SubprocessError,
            json.JSONDecodeError,
        ):
            value = None
        if (
            isinstance(value, dict)
            and value.get("manufacturer")
            and value.get("model")
            and value.get("cpus")
            and value.get("gpus")
        ):
            return value
        if attempt < 2:
            time.sleep(0.1 * (attempt + 1))
    return None


def host_hardware() -> dict[str, Any]:
    physical_memory = _windows_physical_memory()
    if physical_memory is None and hasattr(os, "sysconf"):
        try:
            physical_memory = int(
                os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES")
            )
        except (ValueError, OSError):
            physical_memory = None
    return {
        "machine": platform.machine(),
        "processor": (
            platform.processor()
            or os.environ.get("PROCESSOR_IDENTIFIER")
            or None
        ),
        "logicalCpuCount": os.cpu_count(),
        "physicalMemoryBytes": physical_memory,
        "display": _display_size(),
        "hostname": platform.node(),
        "machineIdentity": _windows_machine_identity(),
    }


def normalized_hardware_identity(environment: dict[str, Any]) -> dict[str, Any]:
    """Return the release-relevant, stable hardware/runtime identity."""

    host = environment.get("hostHardware", {})
    machine = host.get("machineIdentity", {})
    software = environment.get("operatingSystem", {})
    browser = environment.get("browser", {})

    def records(name: str, fields: tuple[str, ...]) -> list[dict[str, Any]]:
        values = machine.get(name, []) if isinstance(machine, dict) else []
        if not isinstance(values, list):
            return []
        normalized = [
            {field: item.get(field) for field in fields}
            for item in values
            if isinstance(item, dict)
        ]
        return sorted(
            normalized,
            key=lambda item: tuple(str(item.get(field) or "") for field in fields),
        )

    return {
        "schemaVersion": "facility-layout-benchmark-hardware-identity-v1",
        "machine": {
            "manufacturer": machine.get("manufacturer")
            if isinstance(machine, dict)
            else None,
            "model": machine.get("model")
            if isinstance(machine, dict)
            else None,
        },
        "cpus": records(
            "cpus",
            ("name", "cores", "logicalProcessors"),
        ),
        "gpus": records(
            "gpus",
            ("name", "adapterRam", "driverVersion"),
        ),
        "logicalCpuCount": host.get("logicalCpuCount"),
        "physicalMemoryBytes": host.get("physicalMemoryBytes"),
        "operatingSystem": {
            "system": software.get("system"),
            "release": software.get("release"),
            "version": software.get("version"),
        },
        "browser": {
            "name": browser.get("name"),
            "version": browser.get("version"),
        },
    }


def hardware_identity_fingerprint(identity: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json_bytes(identity)).hexdigest()


def software_environment() -> dict[str, Any]:
    try:
        playwright_version = importlib.metadata.version("playwright")
    except importlib.metadata.PackageNotFoundError:
        playwright_version = None
    return {
        "operatingSystem": {
            "platform": platform.platform(),
            "system": platform.system(),
            "release": platform.release(),
            "version": platform.version(),
        },
        "python": sys.version,
        "playwright": playwright_version,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the real Facility Layout workspace, top-plan, session, "
            "and Three adapters against P4/P5 fixtures."
        )
    )
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--headed", action="store_true")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--edge-path", type=Path, default=DEFAULT_EDGE)
    parser.add_argument("--output-dir", type=Path, default=PERFORMANCE_DIR)
    parser.add_argument("--artifact-prefix", default=None)
    args = parser.parse_args()
    if args.headed and args.headless:
        parser.error("--headed and --headless are mutually exclusive")
    if args.artifact_prefix is None:
        args.artifact_prefix = (
            "facility-layout-release-performance-smoke"
            if args.smoke
            else "facility-layout-release-performance"
        )
    if not args.artifact_prefix.strip():
        parser.error("--artifact-prefix must be non-empty")
    return args


class NetworkRecorder:
    def __init__(self, origin: str):
        self.origin = origin
        self.external_attempts: list[dict[str, Any]] = []
        self.local_failed_requests: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.page_errors: list[dict[str, str]] = []
        self.console_errors: list[dict[str, str]] = []
        self.request_urls: list[str] = []

    def configure_context(self, context: BrowserContext) -> None:
        def route_request(route: Any) -> None:
            request = route.request
            self.request_urls.append(request.url)
            if request.url.startswith(self.origin):
                route.continue_()
                return
            self.external_attempts.append(
                {
                    "method": request.method,
                    "resourceType": request.resource_type,
                    "url": request.url,
                }
            )
            route.abort()

        context.route("**/*", route_request)

    def configure_page(self, page: Page, label: str) -> None:
        def response_handler(response: Any) -> None:
            if not response.url.startswith(self.origin):
                return
            headers = response.headers
            self.responses.append(
                {
                    "page": label,
                    "status": response.status,
                    "url": response.url,
                    "contentLength": headers.get("content-length"),
                    "contentEncoding": headers.get("content-encoding"),
                    "cacheControl": headers.get("cache-control"),
                }
            )

        def failed_handler(request: Any) -> None:
            if request.url.startswith(self.origin):
                self.local_failed_requests.append(
                    {
                        "page": label,
                        "url": request.url,
                        "failure": str(request.failure or ""),
                    }
                )

        page.on("response", response_handler)
        page.on("requestfailed", failed_handler)
        page.on(
            "pageerror",
            lambda error: self.page_errors.append(
                {"page": label, "message": str(error)}
            ),
        )
        page.on(
            "console",
            lambda message: (
                self.console_errors.append(
                    {"page": label, "message": message.text}
                )
                if message.type == "error"
                else None
            ),
        )

    def as_dict(self) -> dict[str, Any]:
        return {
            "externalRequestsBlocked": True,
            "attemptedExternalRequests": self.external_attempts,
            "localFailedRequests": self.local_failed_requests,
            "responses": self.responses,
            "pageErrors": self.page_errors,
            "consoleErrors": self.console_errors,
            "requestCount": len(self.request_urls),
        }


def configure_cdp_network(
    context: BrowserContext,
    page: Page,
    *,
    network_profile: str,
    cache_state: str,
) -> Any:
    config = NETWORK_PROFILES[network_profile]
    cdp = context.new_cdp_session(page)
    cdp.send("Network.enable")
    cdp.send(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "latency": config["latencyMs"],
            "downloadThroughput": config[
                "downloadThroughputBytesPerSecond"
            ],
            "uploadThroughput": config[
                "uploadThroughputBytesPerSecond"
            ],
            "connectionType": config["connectionType"],
        },
    )
    cdp.send(
        "Network.setCacheDisabled",
        {"cacheDisabled": cache_state == "cold"},
    )
    if cache_state == "cold":
        cdp.send("Network.clearBrowserCache")
    return cdp


def open_page(
    context: BrowserContext,
    recorder: NetworkRecorder,
    url: str,
    *,
    label: str,
    network_profile: str = "local",
    cache_state: str = "warm",
) -> tuple[Page, Any]:
    page = context.new_page()
    recorder.configure_page(page, label)
    cdp = configure_cdp_network(
        context,
        page,
        network_profile=network_profile,
        cache_state=cache_state,
    )
    page.goto(url, wait_until="load", timeout=60_000)
    page.wait_for_function(
        """() => {
            const api = window.facilityReleasePerformance;
            return Boolean(api && (
                api.state.status === 'ready'
                || api.state.status === 'error'
            ));
        }""",
        timeout=60_000,
    )
    status = page.evaluate("() => window.facilityReleasePerformance.state")
    if status["status"] != "ready":
        raise RuntimeError(
            f"Facility benchmark page failed to boot: {status['errors']}"
        )
    return page, cdp


def collect_precise_memory(page: Page, cdp: Any) -> dict[str, Any]:
    cdp.send("HeapProfiler.enable")
    cdp.send("HeapProfiler.collectGarbage")
    browser_memory = page.evaluate(
        "() => window.facilityReleasePerformance.preciseMemory()"
    )
    heap_usage = cdp.send("Runtime.getHeapUsage")
    required = (
        browser_memory.get("usedJSHeapSize"),
        browser_memory.get("totalJSHeapSize"),
        browser_memory.get("jsHeapSizeLimit"),
        heap_usage.get("usedSize"),
        heap_usage.get("totalSize"),
        heap_usage.get("backingStorageSize"),
    )
    if any(not isinstance(value, (int, float)) for value in required):
        raise RuntimeError("Precise JS heap metrics are unavailable.")
    return {
        "performanceMemory": browser_memory,
        "cdpRuntimeHeapUsage": {
            "usedSize": heap_usage["usedSize"],
            "totalSize": heap_usage["totalSize"],
            "embedderHeapUsedSize": heap_usage.get("embedderHeapUsedSize"),
            "backingStorageSize": heap_usage["backingStorageSize"],
        },
    }


def drive_three_interaction(
    page: Page,
    canvas_rect: dict[str, float],
    duration_seconds: float,
) -> dict[str, Any]:
    duration_seconds = max(0.01, duration_seconds)
    x0 = float(canvas_rect["x"]) + float(canvas_rect["width"]) * 0.52
    y0 = float(canvas_rect["y"]) + float(canvas_rect["height"]) * 0.48
    radius_x = max(16.0, float(canvas_rect["width"]) * 0.12)
    radius_y = max(12.0, float(canvas_rect["height"]) * 0.08)
    total_started = time.perf_counter()
    half = duration_seconds / 2
    operations: list[dict[str, Any]] = []

    def drag(button: str, phase_start: float, phase_duration: float) -> None:
        page.mouse.move(x0, y0)
        page.mouse.down(button=button)
        event_count = 0
        started = time.perf_counter()
        while time.perf_counter() - phase_start < phase_duration:
            elapsed = time.perf_counter() - phase_start
            angle = elapsed * 5.1
            page.mouse.move(
                x0 + math.sin(angle) * radius_x,
                y0 + math.cos(angle * 0.73) * radius_y,
                steps=2,
            )
            event_count += 1
            time.sleep(0.003)
        page.mouse.up(button=button)
        operations.append(
            {
                "interaction": "orbit" if button == "left" else "pan",
                "button": button,
                "eventBatches": event_count,
                "wallDurationMs": (time.perf_counter() - started) * 1000,
            }
        )

    drag("left", total_started, half)
    second_started = time.perf_counter()
    drag("right", second_started, duration_seconds - half)
    return {
        "requestedDurationMs": duration_seconds * 1000,
        "wallDurationMs": (time.perf_counter() - total_started) * 1000,
        "operations": operations,
    }


def run_core_measurements(
    browser: Browser,
    recorder: NetworkRecorder,
    benchmark_url: str,
    protocol: dict[str, Any],
) -> dict[str, Any]:
    context = browser.new_context(
        viewport={"width": 1440, "height": 960},
        device_scale_factor=1,
        reduced_motion="reduce",
    )
    recorder.configure_context(context)
    page: Page | None = None
    try:
        page, cdp = open_page(
            context,
            recorder,
            benchmark_url,
            label="core",
        )
        mount_evidence = page.evaluate(
            "() => window.facilityReleasePerformance.mount("
            "{profile: 'full-detail'})"
        )
        environment = {
            "browser": mount_evidence["browser"],
            "webgl": mount_evidence["webgl"],
        }
        precise_memory = collect_precise_memory(page, cdp)
        discrete = protocol["discrete"]
        plan_render = page.evaluate(
            """options => (
                window.facilityReleasePerformance.runPlanRenderLatency(options)
            )""",
            {
                "warmups": discrete["discardedWarmups"],
                "iterations": discrete["measuredIterations"],
            },
        )
        picking = page.evaluate(
            """options => (
                window.facilityReleasePerformance.runPicking(options)
            )""",
            {
                "warmups": discrete["discardedWarmups"],
                "iterations": discrete["measuredIterations"],
                "preferredPlacementId": "pl-rack-06",
            },
        )
        idle = page.evaluate(
            """options => (
                window.facilityReleasePerformance.measureIdleStop(options)
            )""",
            {
                "warmups": discrete["discardedWarmups"],
                "iterations": discrete["measuredIterations"],
                "quietWindowMs": protocol["idleQuietWindowMs"],
            },
        )

        frame = protocol["frame"]
        plan_frames = []
        for run_index in range(frame["runsPerScenario"]):
            plan_frames.append(
                {
                    "runIndex": run_index,
                    **page.evaluate(
                        """options => (
                            window.facilityReleasePerformance
                                .runPlanFrames(options)
                        )""",
                        {
                            "warmupMs": (
                                frame["warmupSecondsPerRun"] * 1000
                            ),
                            "durationMs": (
                                frame["measuredSecondsPerRun"] * 1000
                            ),
                        },
                    ),
                }
            )

        three_frames = []
        for run_index in range(frame["runsPerScenario"]):
            prepared = page.evaluate(
                "() => window.facilityReleasePerformance"
                ".prepareThreeInteraction()"
            )
            if frame["warmupSecondsPerRun"] > 0:
                drive_three_interaction(
                    page,
                    prepared["canvasRect"],
                    frame["warmupSecondsPerRun"],
                )
            page.evaluate(
                "() => window.facilityReleasePerformance.startFrameCapture()"
            )
            interaction = drive_three_interaction(
                page,
                prepared["canvasRect"],
                frame["measuredSecondsPerRun"],
            )
            pick_point = page.evaluate(
                "() => window.facilityReleasePerformance"
                ".findPickPoint('pl-rack-06')"
            )
            if not pick_point:
                raise RuntimeError("No real 3D pick point is available.")
            select_started = time.perf_counter()
            page.mouse.click(
                float(pick_point["clientX"]),
                float(pick_point["clientY"]),
            )
            select_duration_ms = (
                time.perf_counter() - select_started
            ) * 1000
            page.wait_for_function(
                """placementId => {
                    const snapshot = window.facilityReleasePerformance
                        .snapshot();
                    return snapshot
                        && snapshot.selection.includes(placementId);
                }""",
                arg=pick_point["placementId"],
                timeout=10_000,
            )
            captured = page.evaluate(
                "() => window.facilityReleasePerformance.stopFrameCapture()"
            )
            before_camera = captured["before"]["threeDiagnostics"]["camera"]
            after_camera = captured["after"]["threeDiagnostics"]["camera"]
            if before_camera == after_camera:
                raise RuntimeError(
                    "Orbit/pan input did not change the real Three camera."
                )
            three_frames.append(
                {
                    "runIndex": run_index,
                    **captured,
                    "interaction": interaction,
                    "selection": {
                        "durationMs": select_duration_ms,
                        "placementId": pick_point["placementId"],
                        "sessionSelection": captured["after"]["selection"],
                        "synchronized": (
                            pick_point["placementId"]
                            in captured["after"]["selection"]
                            and pick_point["placementId"]
                            in captured["after"]["threeDiagnostics"][
                                "selectedPlacementIds"
                            ]
                            and pick_point["placementId"]
                            in captured["after"]["topDiagnostics"][
                                "selections"
                            ]
                        ),
                    },
                }
            )

        final_snapshot = page.evaluate(
            "() => window.facilityReleasePerformance.snapshot()"
        )
        destroyed = page.evaluate(
            "() => window.facilityReleasePerformance.destroyRuntime()"
        )
        return {
            "mount": mount_evidence,
            "environment": environment,
            "preciseMemory": precise_memory,
            "planRender": plan_render,
            "planFrames": plan_frames,
            "threeFrames": three_frames,
            "picking": picking,
            "idleRenderStop": idle,
            "finalSnapshot": final_snapshot,
            "destroy": destroyed,
        }
    finally:
        if page is not None and not page.is_closed():
            page.close()
        context.close()


def run_asset_loading(
    browser: Browser,
    recorder: NetworkRecorder,
    benchmark_url: str,
    protocol: dict[str, Any],
) -> list[dict[str, Any]]:
    config = protocol["assetLoading"]
    samples: list[dict[str, Any]] = []
    for network_profile in config["networkProfiles"]:
        for cache_state in config["cacheStates"]:
            context = browser.new_context(
                viewport={"width": 1440, "height": 960},
                device_scale_factor=1,
                reduced_motion="reduce",
            )
            recorder.configure_context(context)
            try:
                total = (
                    config["discardedWarmupsPerCondition"]
                    + config["measuredIterationsPerCondition"]
                )
                for iteration in range(total):
                    page: Page | None = None
                    label = (
                        f"load-{network_profile}-{cache_state}-{iteration}"
                    )
                    try:
                        page, _cdp = open_page(
                            context,
                            recorder,
                            benchmark_url,
                            label=label,
                            network_profile=network_profile,
                            cache_state=cache_state,
                        )
                        before_responses = len(recorder.responses)
                        evidence = page.evaluate(
                            "() => window.facilityReleasePerformance.mount("
                            "{profile: 'full-detail'})"
                        )
                        after_responses = recorder.responses[
                            before_responses:
                        ]
                        destroyed = page.evaluate(
                            "() => window.facilityReleasePerformance"
                            ".destroyRuntime()"
                        )
                        if iteration >= config[
                            "discardedWarmupsPerCondition"
                        ]:
                            samples.append(
                                {
                                    "networkProfile": network_profile,
                                    "networkEmulation": deepcopy(
                                        NETWORK_PROFILES[network_profile]
                                    ),
                                    "cacheState": cache_state,
                                    "iteration": (
                                        iteration
                                        - config[
                                            "discardedWarmupsPerCondition"
                                        ]
                                    ),
                                    "load": evidence["load"],
                                    "snapshot": evidence["snapshot"],
                                    "httpResponses": after_responses,
                                    "destroy": destroyed,
                                }
                            )
                    finally:
                        if page is not None and not page.is_closed():
                            page.close()
            finally:
                context.close()
    return samples


def run_remount_memory(
    browser: Browser,
    recorder: NetworkRecorder,
    benchmark_url: str,
    protocol: dict[str, Any],
) -> list[dict[str, Any]]:
    config = protocol["remount"]
    sequences: list[dict[str, Any]] = []
    for sequence_index in range(config["independentSequences"]):
        context_id = str(uuid.uuid4())
        context = browser.new_context(
            viewport={"width": 1440, "height": 960},
            device_scale_factor=1,
            reduced_motion="reduce",
        )
        recorder.configure_context(context)
        page: Page | None = None
        try:
            page, cdp = open_page(
                context,
                recorder,
                benchmark_url,
                label=f"remount-{sequence_index}",
            )
            initial_mount = page.evaluate(
                "() => window.facilityReleasePerformance.mount({ profile: 'proxy' })"
            )
            page.wait_for_timeout(config["quiescenceMsBeforeMemorySample"])
            before = collect_precise_memory(page, cdp)
            cycle_samples = []
            for cycle_index in range(config["cyclesPerSequence"]):
                started = time.perf_counter()
                lifecycle = page.evaluate(
                    "() => window.facilityReleasePerformance.remountOnce()"
                )
                cycle_samples.append(
                    {
                        "cycleIndex": cycle_index,
                        "wallDurationMs": (
                            time.perf_counter() - started
                        ) * 1000,
                        "lifecycle": lifecycle,
                    }
                )
            page.wait_for_timeout(config["quiescenceMsBeforeMemorySample"])
            after = collect_precise_memory(page, cdp)
            before_used = before["performanceMemory"]["usedJSHeapSize"]
            after_used = after["performanceMemory"]["usedJSHeapSize"]
            growth_bytes = after_used - before_used
            growth_percent = (
                (growth_bytes / before_used) * 100
                if before_used > 0
                else None
            )
            sequences.append(
                {
                    "sequenceIndex": sequence_index,
                    "browserContextId": context_id,
                    "freshBrowserContext": True,
                    "initialMount": initial_mount,
                    "discardedWarmups": config[
                        "discardedWarmupsPerSequence"
                    ],
                    "cycleCount": config["cyclesPerSequence"],
                    "preciseMemoryInfo": True,
                    "before": before,
                    "cycles": cycle_samples,
                    "after": after,
                    "growthBytes": growth_bytes,
                    "growthPercent": growth_percent,
                }
            )
        finally:
            if page is not None and not page.is_closed():
                page.close()
            context.close()
    return sequences


def required_source_paths() -> tuple[Path, ...]:
    return tuple(path for _source_id, path, _role in source_specs())


def validate_required_inputs(edge_path: Path) -> list[str]:
    errors = [
        f"missing_input:{path.relative_to(ROOT).as_posix()}"
        for path in required_source_paths()
        if not path.is_file()
    ]
    if not edge_path.is_file():
        errors.append(f"missing_browser:{edge_path}")
    return errors


def _source_validation_errors(
    raw: dict[str, Any],
    source_root: Path,
) -> list[str]:
    errors = []
    records = raw.get("source", {}).get("files")
    if not isinstance(records, list) or not records:
        return ["source_files_missing"]
    expected = {
        source_id: {
            "path": path.relative_to(ROOT).as_posix(),
            "role": role,
        }
        for source_id, path, role in source_specs()
    }
    identifiers = set()
    for record in records:
        source_id = record.get("sourceId")
        if not isinstance(source_id, str) or not source_id:
            errors.append("source_id_missing")
            continue
        if source_id in identifiers:
            errors.append(f"source_id_duplicate:{source_id}")
        identifiers.add(source_id)
        expected_record = expected.get(source_id)
        if expected_record is None:
            errors.append(f"unexpected_source_id:{source_id}")
            continue
        relative = record.get("path")
        if not isinstance(relative, str) or not relative:
            errors.append(f"source_path_missing:{source_id}")
            continue
        expected_relative = expected_record["path"]
        if relative != expected_relative:
            errors.append(f"source_path_mismatch:{source_id}")
        if record.get("role") != expected_record["role"]:
            errors.append(f"source_role_mismatch:{source_id}")
        path = source_root / Path(expected_relative)
        if not path.is_file():
            errors.append(f"source_file_missing:{source_id}")
            continue
        if record.get("byteLength") != path.stat().st_size:
            errors.append(f"source_size_mismatch:{source_id}")
        if record.get("sha256") != sha256_file(path):
            errors.append(f"source_hash_mismatch:{source_id}")
    required_ids = set(expected)
    missing = sorted(required_ids - identifiers)
    errors.extend(f"required_source_missing:{item}" for item in missing)
    return errors


def validate_raw_artifact(
    raw: dict[str, Any],
    *,
    source_root: Path = ROOT,
) -> list[str]:
    errors: list[str] = []
    if raw.get("schemaVersion") != RAW_SCHEMA:
        errors.append("invalid_raw_schema")
    protocol = raw.get("protocol")
    if not isinstance(protocol, dict):
        errors.append("protocol_missing")
        return errors
    profile = protocol.get("profile")
    if profile not in {"smoke", "release"}:
        errors.append("invalid_profile")
    if profile == "smoke" and protocol.get("releaseEligible") is not False:
        errors.append("smoke_must_not_be_release_eligible")
    if profile == "release":
        expected = protocol_for(False)
        if protocol != expected:
            errors.append("release_protocol_does_not_match_section_18_3")

    errors.extend(_source_validation_errors(raw, source_root))

    network = raw.get("network", {})
    if network.get("externalRequestsBlocked") is not True:
        errors.append("external_request_blocking_not_enabled")
    if network.get("attemptedExternalRequests"):
        errors.append("external_request_attempted")
    if network.get("localFailedRequests"):
        errors.append("local_request_failed")
    if network.get("pageErrors"):
        errors.append("browser_page_error")
    if network.get("consoleErrors"):
        errors.append("browser_console_error")

    recorded_errors = raw.get("errors")
    if not isinstance(recorded_errors, list):
        errors.append("run_errors_missing")
    elif recorded_errors:
        errors.append("benchmark_run_error")
    unavailable = raw.get("unavailableRequiredMeasurements")
    if not isinstance(unavailable, list):
        errors.append("required_measurement_availability_missing")
    elif unavailable:
        errors.append("required_measurement_unavailable")

    environment = raw.get("environment", {})
    host = environment.get("hostHardware", {})
    if not isinstance(host.get("logicalCpuCount"), int):
        errors.append("host_cpu_count_unavailable")
    if not isinstance(host.get("physicalMemoryBytes"), int):
        errors.append("host_memory_unavailable")
    identity = host.get("machineIdentity")
    if platform.system() == "Windows":
        if not isinstance(identity, dict):
            errors.append("host_machine_identity_unavailable")
        else:
            if not identity.get("manufacturer") or not identity.get("model"):
                errors.append("host_make_model_unavailable")
            if not identity.get("cpus") or not all(
                item.get("name") for item in identity.get("cpus", [])
            ):
                errors.append("host_cpu_model_unavailable")
            if not identity.get("gpus") or not all(
                item.get("name") for item in identity.get("gpus", [])
            ):
                errors.append("host_gpu_model_unavailable")
    browser = environment.get("browser", {})
    browser_runtime = browser.get("runtime", {})
    webgl = browser.get("webgl", {})
    if not browser.get("version"):
        errors.append("browser_version_unavailable")
    if not browser_runtime.get("userAgent"):
        errors.append("browser_user_agent_unavailable")
    if not webgl.get("renderer") or not webgl.get("version"):
        errors.append("webgl_hardware_information_unavailable")
    expected_hardware_identity = normalized_hardware_identity(environment)
    if environment.get("hardwareIdentity") != expected_hardware_identity:
        errors.append("hardware_identity_mismatch")
    expected_hardware_fingerprint = hardware_identity_fingerprint(
        expected_hardware_identity
    )
    if (
        environment.get("hardwareFingerprintSha256")
        != expected_hardware_fingerprint
    ):
        errors.append("hardware_fingerprint_mismatch")

    samples = raw.get("samples", {})
    plan_render = samples.get("planRender", {})
    layer_facts = plan_render.get("layerFacts", {})
    layout_counts = layer_facts.get("layoutCounts", {})
    rendered_counts = layer_facts.get("renderedCounts", {})
    for layer in ("placements", "zones", "routes"):
        if not isinstance(layout_counts.get(layer), int):
            errors.append(f"plan_layout_count_missing:{layer}")
        elif layout_counts[layer] < 1:
            errors.append(f"plan_layout_layer_empty:{layer}")
        if rendered_counts.get(layer) != layout_counts.get(layer):
            errors.append(f"plan_rendered_count_mismatch:{layer}")
    labels = layer_facts.get("labels", {})
    if labels.get("accessibilityLabelsSupported") is not True:
        errors.append("plan_accessibility_labels_not_measured")
    if not isinstance(labels.get("accessibilityLabelCount"), int):
        errors.append("plan_accessibility_label_count_missing")
    if labels.get("visibleTextLabelsSupported") is False:
        if not labels.get("unavailableReason"):
            errors.append("visible_label_unavailability_not_explained")
    clearances = layer_facts.get("clearances", {})
    if clearances.get("routeCorridorsSupported") is not True:
        errors.append("route_corridors_not_measured")
    if not isinstance(clearances.get("routeCorridorCount"), int):
        errors.append("route_corridor_count_missing")
    if clearances.get("placementClearanceVolumesSupported") is False:
        if not clearances.get("unavailableReason"):
            errors.append("clearance_unavailability_not_explained")

    discrete_expected = protocol.get("discrete", {}).get(
        "measuredIterations"
    )
    render_samples = plan_render.get("samples")
    if not isinstance(render_samples, list):
        errors.append("plan_render_samples_missing")
    elif len(render_samples) != discrete_expected:
        errors.append("plan_render_sample_count_mismatch")

    plan_frames = samples.get("planFrames")
    three_frames = samples.get("threeFrames")
    expected_frame_runs = protocol.get("frame", {}).get(
        "runsPerScenario"
    )
    for name, runs in (("plan", plan_frames), ("three", three_frames)):
        if not isinstance(runs, list):
            errors.append(f"{name}_frame_runs_missing")
            continue
        if len(runs) != expected_frame_runs:
            errors.append(f"{name}_frame_run_count_mismatch")
        if any(not run.get("frameIntervalsMs") for run in runs):
            errors.append(f"{name}_frame_samples_missing")
    if isinstance(three_frames, list):
        for run in three_frames:
            interaction = run.get("interaction", {})
            kinds = {
                item.get("interaction")
                for item in interaction.get("operations", [])
            }
            if kinds != {"orbit", "pan"}:
                errors.append("three_orbit_pan_evidence_missing")
            if run.get("selection", {}).get("synchronized") is not True:
                errors.append("three_selection_not_synchronized")
            before_camera = (
                run.get("before", {})
                .get("threeDiagnostics", {})
                .get("camera")
            )
            after_camera = (
                run.get("after", {})
                .get("threeDiagnostics", {})
                .get("camera")
            )
            if not before_camera or before_camera == after_camera:
                errors.append("three_camera_did_not_move")

    picking = samples.get("picking", {})
    pick_samples = picking.get("samples")
    if not isinstance(pick_samples, list):
        errors.append("picking_samples_missing")
    elif len(pick_samples) != discrete_expected:
        errors.append("picking_sample_count_mismatch")
    elif any(
        not isinstance(item.get("durationMs"), (int, float))
        or not item.get("placementId")
        for item in pick_samples
    ):
        errors.append("picking_measurement_invalid")

    idle = samples.get("idleRenderStop", {})
    idle_samples = idle.get("samples")
    if not isinstance(idle_samples, list):
        errors.append("idle_render_samples_missing")
    elif len(idle_samples) != discrete_expected:
        errors.append("idle_render_sample_count_mismatch")
    elif any(
        not isinstance(item.get("stopLatencyMs"), (int, float))
        or item.get("activeAdapterFrames") != 0
        or item.get("stableAfter", {}).get("pendingFrame") is not False
        for item in idle_samples
    ):
        errors.append("idle_render_measurement_invalid")

    load_samples = samples.get("assetLoading")
    if not isinstance(load_samples, list) or not load_samples:
        errors.append("asset_loading_samples_missing")
    else:
        expected_load_count = (
            len(protocol["assetLoading"]["networkProfiles"])
            * len(protocol["assetLoading"]["cacheStates"])
            * protocol["assetLoading"]["measuredIterationsPerCondition"]
        )
        if len(load_samples) != expected_load_count:
            errors.append("asset_loading_sample_count_mismatch")
        expected_conditions = {
            (network, cache): protocol["assetLoading"][
                "measuredIterationsPerCondition"
            ]
            for network in protocol["assetLoading"]["networkProfiles"]
            for cache in protocol["assetLoading"]["cacheStates"]
        }
        actual_conditions: dict[tuple[str, str], int] = {}
        for sample in load_samples:
            key = (
                sample.get("networkProfile"),
                sample.get("cacheState"),
            )
            actual_conditions[key] = actual_conditions.get(key, 0) + 1
        if actual_conditions != expected_conditions:
            errors.append("asset_loading_condition_matrix_mismatch")
        for sample in load_samples:
            stages = sample.get("load", {}).get("stages", [])
            if [item.get("stage") for item in stages] != list(
                REQUIRED_PROGRESSIVE_STAGES
            ):
                errors.append("progressive_stage_order_invalid")
                continue
            if any(item.get("status") != "resolved" for item in stages):
                errors.append("progressive_stage_unresolved")
            if any(
                not isinstance(item.get("durationMs"), (int, float))
                for item in stages
            ):
                errors.append("progressive_stage_timing_missing")
            detail_stage = next(
                (
                    item
                    for item in stages
                    if item.get("stage") == "detail"
                ),
                {},
            )
            allocation = detail_stage.get("visualAllocation") or {}
            if allocation.get("available") is not True:
                errors.append("gpu_allocation_estimate_unavailable")
            if not isinstance(
                allocation.get("estimatedGpuAllocationBytes"),
                (int, float),
            ):
                errors.append("gpu_allocation_estimate_missing")
            resources = sample.get("load", {}).get("resources")
            if not isinstance(resources, list) or not any(
                str(item.get("name", "")).endswith(".glb")
                for item in resources
            ):
                errors.append("asset_resource_timing_missing")

    remount = samples.get("remountMemory")
    remount_protocol = protocol.get("remount", {})
    if not isinstance(remount, list):
        errors.append("remount_sequences_missing")
    else:
        if len(remount) != remount_protocol.get("independentSequences"):
            errors.append("remount_sequence_count_mismatch")
        context_ids = {
            item.get("browserContextId") for item in remount
        }
        if len(context_ids) != len(remount) or None in context_ids:
            errors.append("remount_contexts_not_independent")
        for sequence in remount:
            if sequence.get("freshBrowserContext") is not True:
                errors.append("remount_context_not_fresh")
            initial_mount = sequence.get("initialMount")
            if (
                not isinstance(initial_mount, dict)
                or initial_mount.get("snapshot", {})
                .get("dom", {})
                .get("canvases")
                != 1
            ):
                errors.append("remount_initial_mount_missing")
            initial_pool = (
                initial_mount or {}
            ).get("snapshot", {}).get("rendererPool", {})
            if (
                initial_pool.get("createdCount") != 1
                or initial_pool.get("leasedCount") != 1
                or initial_pool.get("availableCount") != 0
            ):
                errors.append("remount_renderer_pool_initial_state_invalid")
            if sequence.get("cycleCount") != remount_protocol.get(
                "cyclesPerSequence"
            ):
                errors.append("remount_cycle_count_mismatch")
            if sequence.get("preciseMemoryInfo") is not True:
                errors.append("precise_remount_memory_not_used")
            if len(sequence.get("cycles", [])) != sequence.get(
                "cycleCount"
            ):
                errors.append("remount_cycle_samples_missing")
            if remount_protocol.get("lifecycleMode") != (
                "bounded-suspend-resume"
            ):
                errors.append("remount_lifecycle_mode_invalid")
            for memory_point in (
                sequence.get("before"),
                sequence.get("after"),
            ):
                performance_memory = (
                    memory_point or {}
                ).get("performanceMemory", {})
                cdp_memory = (
                    memory_point or {}
                ).get("cdpRuntimeHeapUsage", {})
                if not isinstance(
                    performance_memory.get("usedJSHeapSize"),
                    (int, float),
                ):
                    errors.append("precise_js_heap_value_missing")
                if not isinstance(
                    cdp_memory.get("backingStorageSize"),
                    (int, float),
                ):
                    errors.append("arraybuffer_memory_value_missing")
            if not isinstance(sequence.get("growthPercent"), (int, float)):
                errors.append("remount_heap_growth_missing")
            before_used = (
                sequence.get("before", {})
                .get("performanceMemory", {})
                .get("usedJSHeapSize")
            )
            after_used = (
                sequence.get("after", {})
                .get("performanceMemory", {})
                .get("usedJSHeapSize")
            )
            stored_growth = sequence.get("growthPercent")
            stored_growth_bytes = sequence.get("growthBytes")
            if (
                isinstance(before_used, (int, float))
                and isinstance(after_used, (int, float))
                and before_used > 0
            ):
                expected_growth_bytes = after_used - before_used
                expected_growth = (expected_growth_bytes / before_used) * 100
                if (
                    not isinstance(stored_growth_bytes, (int, float))
                    or not math.isclose(
                        float(stored_growth_bytes),
                        float(expected_growth_bytes),
                        rel_tol=0.0,
                        abs_tol=1e-6,
                    )
                    or not isinstance(stored_growth, (int, float))
                    or not math.isclose(
                        float(stored_growth),
                        float(expected_growth),
                        rel_tol=1e-12,
                        abs_tol=1e-9,
                    )
                ):
                    errors.append("remount_heap_growth_mismatch")
            elif isinstance(before_used, (int, float)) and before_used <= 0:
                errors.append("remount_heap_baseline_invalid")
            for cycle in sequence.get("cycles", []):
                lifecycle = cycle.get("lifecycle", {})
                if lifecycle.get("lifecycleMode") != (
                    "bounded-suspend-resume"
                ):
                    errors.append("remount_lifecycle_mode_invalid")
                suspended = lifecycle.get("suspended", {})
                if suspended.get("suspended") is not True:
                    errors.append("remount_workspace_suspend_invalid")
                if any(
                    suspended.get(field) != 0
                    for field in (
                        "workspaceRoots",
                        "canvases",
                        "planSvgs",
                        "rootChildren",
                        "activeObserverTargets",
                        "activeAdapterFrames",
                    )
                ):
                    errors.append("remount_lifecycle_leak")
                suspended_pool = suspended.get("rendererPool", {})
                if (
                    suspended_pool.get("createdCount") != 1
                    or suspended_pool.get("leasedCount") != 1
                    or suspended_pool.get("availableCount") != 0
                ):
                    errors.append("remount_renderer_pool_suspend_invalid")
                three_after = suspended.get("threeAfter", {})
                if (
                    three_after.get("suspended") is not True
                    or three_after.get("lifecycle", {}).get(
                        "observerActive"
                    ) is not False
                    or three_after.get("demandRendering", {}).get(
                        "pendingFrame"
                    ) is not False
                ):
                    errors.append("remount_three_suspend_invalid")
                mounted = lifecycle.get("mounted", {})
                if (
                    mounted.get("dom", {}).get("canvases") != 1
                    or mounted.get("dom", {}).get("planSvgs") != 1
                ):
                    errors.append("remount_live_workspace_missing")
                mounted_pool = mounted.get("rendererPool", {})
                if (
                    mounted_pool.get("createdCount") != 1
                    or mounted_pool.get("leasedCount") != 1
                    or mounted_pool.get("availableCount") != 0
                ):
                    errors.append("remount_renderer_pool_resume_invalid")

    core = samples.get("core", {})
    module_proof = (
        core.get("mount", {})
        .get("snapshot", {})
        .get("moduleProof", {})
    )
    for field in (
        "actualWorkspace",
        "actualTopPlanAdapter",
        "actualThreeAdapter",
    ):
        if module_proof.get(field) is not True:
            errors.append(f"actual_adapter_proof_missing:{field}")
    precise = core.get("preciseMemory", {}).get(
        "performanceMemory", {}
    )
    if precise.get("source") != "performance.memory":
        errors.append("precise_memory_source_invalid")

    if profile == "release":
        minimum_frames = protocol["frame"]["minimumMeasuredFramesTotal"]
        for name, runs in (("plan", plan_frames), ("three", three_frames)):
            if isinstance(runs, list):
                frame_count = sum(
                    len(run.get("frameIntervalsMs", [])) for run in runs
                )
                if frame_count < minimum_frames:
                    errors.append(
                        f"{name}_minimum_frame_count_not_met"
                    )
    return sorted(set(errors))


def _frame_summary(runs: list[dict[str, Any]]) -> dict[str, Any]:
    intervals = [
        float(value)
        for run in runs
        for value in run.get("frameIntervalsMs", [])
    ]
    callbacks = [
        float(value)
        for run in runs
        for value in run.get("callbackDurationsMs", [])
    ]
    long_tasks = [
        item
        for run in runs
        for item in run.get("longTasks", [])
    ]
    wall_ms = sum(float(run.get("wallDurationMs", 0)) for run in runs)
    return {
        "runCount": len(runs),
        "frameIntervals": latency_summary(intervals),
        "callbackDurations": latency_summary(callbacks),
        "measuredWallDurationMs": rounded(wall_ms),
        "effectiveFps": rounded(
            len(intervals) * 1000 / wall_ms if wall_ms else None
        ),
        "framesOver22Ms": sum(value > 22 for value in intervals),
        "framesOver33Ms": sum(value > 33 for value in intervals),
        "longTaskCount": len(long_tasks),
        "maximumLongTaskMs": rounded(
            max(
                (float(item.get("durationMs", 0)) for item in long_tasks),
                default=0,
            )
        ),
    }


def _asset_loading_summary(
    samples: list[dict[str, Any]],
) -> dict[str, Any]:
    grouped: dict[str, Any] = {}
    for sample in samples:
        key = f"{sample['networkProfile']}:{sample['cacheState']}"
        group = grouped.setdefault(
            key,
            {
                "networkProfile": sample["networkProfile"],
                "cacheState": sample["cacheState"],
                "total": [],
                "stages": {
                    stage: [] for stage in REQUIRED_PROGRESSIVE_STAGES
                },
                "transferredBytes": [],
                "encodedBodyBytes": [],
            },
        )
        group["total"].append(
            float(sample["load"]["totalDurationMs"])
        )
        for stage in sample["load"]["stages"]:
            group["stages"][stage["stage"]].append(
                float(stage["durationMs"])
            )
        resources = sample["load"]["resources"]
        group["transferredBytes"].append(
            sum(int(item.get("transferSize") or 0) for item in resources)
        )
        group["encodedBodyBytes"].append(
            sum(int(item.get("encodedBodySize") or 0) for item in resources)
        )
    result = {}
    for key, group in grouped.items():
        result[key] = {
            "networkProfile": group["networkProfile"],
            "cacheState": group["cacheState"],
            "total": latency_summary(group["total"]),
            "stages": {
                stage: latency_summary(values)
                for stage, values in group["stages"].items()
            },
            "transferredBytes": {
                "median": rounded(percentile(group["transferredBytes"], 0.5)),
                "maximum": max(group["transferredBytes"], default=0),
            },
            "encodedBodyBytes": {
                "median": rounded(percentile(group["encodedBodyBytes"], 0.5)),
                "maximum": max(group["encodedBodyBytes"], default=0),
            },
        }
    return result


def _budget_check(
    budget_id: str,
    measured: float | int | None,
    limit: float | int,
    unit: str,
    *,
    applicable: bool,
) -> dict[str, Any]:
    return {
        "budgetId": budget_id,
        "measured": measured,
        "limit": limit,
        "unit": unit,
        "available": measured is not None,
        "applicable": applicable,
        "passed": (
            measured is not None and measured <= limit
            if applicable
            else None
        ),
    }


def build_summary(
    raw: dict[str, Any],
    *,
    raw_path: Path | None = None,
    source_root: Path = ROOT,
) -> dict[str, Any]:
    errors = validate_raw_artifact(raw, source_root=source_root)
    samples = raw.get("samples", {})
    plan_frames = _frame_summary(samples.get("planFrames", []))
    three_frames = _frame_summary(samples.get("threeFrames", []))
    plan_render_values = [
        float(item["durationMs"])
        for item in samples.get("planRender", {}).get("samples", [])
        if isinstance(item.get("durationMs"), (int, float))
    ]
    pick_values = [
        float(item["durationMs"])
        for item in samples.get("picking", {}).get("samples", [])
        if isinstance(item.get("durationMs"), (int, float))
    ]
    idle_values = [
        float(item["stopLatencyMs"])
        for item in samples.get("idleRenderStop", {}).get("samples", [])
        if isinstance(item.get("stopLatencyMs"), (int, float))
    ]
    remount_growth = [
        float(item["growthPercent"])
        for item in samples.get("remountMemory", [])
        if isinstance(item.get("growthPercent"), (int, float))
    ]
    remount_heaps = [
        int(point["performanceMemory"]["usedJSHeapSize"])
        for sequence in samples.get("remountMemory", [])
        for point in (sequence.get("before"), sequence.get("after"))
        if point
        and isinstance(
            point.get("performanceMemory", {}).get("usedJSHeapSize"),
            (int, float),
        )
    ]
    renderer_records = []
    core_mount = samples.get("core", {}).get("mount", {})
    if core_mount:
        renderer_records.append(
            core_mount.get("snapshot", {}).get("renderer", {})
        )
    renderer_records.extend(
        run.get("after", {}).get("renderer", {})
        for run in samples.get("threeFrames", [])
    )
    draw_calls = [
        int(record.get("render", {}).get("calls"))
        for record in renderer_records
        if isinstance(record.get("render", {}).get("calls"), (int, float))
    ]
    triangles = [
        int(record.get("render", {}).get("triangles"))
        for record in renderer_records
        if isinstance(
            record.get("render", {}).get("triangles"),
            (int, float),
        )
    ]
    gpu_estimates = [
        int(stage["visualAllocation"]["estimatedGpuAllocationBytes"])
        for sample in samples.get("assetLoading", [])
        for stage in sample.get("load", {}).get("stages", [])
        if stage.get("stage") == "detail"
        and isinstance(stage.get("visualAllocation"), dict)
        and isinstance(
            stage["visualAllocation"].get(
                "estimatedGpuAllocationBytes"
            ),
            (int, float),
        )
    ]
    maximum_long_task = max(
        plan_frames["maximumLongTaskMs"] or 0,
        three_frames["maximumLongTaskMs"] or 0,
    )
    protocol = raw.get("protocol", {})
    release_eligible = protocol.get("releaseEligible") is True
    budgets = [
        _budget_check(
            "plan-frame-p95-standard",
            plan_frames["frameIntervals"]["p95Ms"],
            22,
            "ms",
            applicable=release_eligible,
        ),
        _budget_check(
            "three-frame-p95-standard",
            three_frames["frameIntervals"]["p95Ms"],
            22,
            "ms",
            applicable=release_eligible,
        ),
        _budget_check(
            "three-picking-p95",
            percentile(pick_values, 0.95),
            50,
            "ms",
            applicable=release_eligible,
        ),
        _budget_check(
            "idle-render-stop",
            max(idle_values) if idle_values else None,
            250,
            "ms",
            applicable=release_eligible,
        ),
        _budget_check(
            "memory-growth-after-20-remounts",
            max(remount_growth) if remount_growth else None,
            10,
            "percent",
            applicable=release_eligible,
        ),
        _budget_check(
            "javascript-heap",
            max(remount_heaps) if remount_heaps else None,
            400 * 1024 * 1024,
            "bytes",
            applicable=release_eligible,
        ),
        _budget_check(
            "overview-draw-calls",
            max(draw_calls) if draw_calls else None,
            300,
            "draw_calls",
            applicable=release_eligible,
        ),
        _budget_check(
            "visible-overview-triangles",
            max(triangles) if triangles else None,
            2_000_000,
            "triangles",
            applicable=release_eligible,
        ),
        _budget_check(
            "estimated-gpu-allocation",
            max(gpu_estimates) if gpu_estimates else None,
            512 * 1024 * 1024,
            "bytes",
            applicable=release_eligible,
        ),
        _budget_check(
            "main-thread-long-task",
            maximum_long_task,
            100,
            "ms",
            applicable=release_eligible,
        ),
    ]
    release_gate_met = (
        release_eligible
        and not errors
        and all(item["passed"] is True for item in budgets)
    )
    blockers = list(errors)
    if not release_eligible:
        blockers.append("smoke_profile_not_release_eligible")
    blockers.extend(
        f"budget_failed:{item['budgetId']}"
        for item in budgets
        if release_eligible and item["passed"] is not True
    )
    raw_binding = None
    if raw_path is not None and raw_path.is_file():
        raw_binding = {
            "path": raw_path.relative_to(source_root).as_posix()
            if raw_path.is_relative_to(source_root)
            else str(raw_path),
            "byteLength": raw_path.stat().st_size,
            "sha256": sha256_file(raw_path),
        }
    return {
        "schemaVersion": SUMMARY_SCHEMA,
        "benchmarkId": raw.get("benchmarkId"),
        "generatedAtUtc": raw.get("completedAtUtc"),
        "profile": protocol.get("profile"),
        "releaseEligible": release_eligible,
        "releaseGateMet": release_gate_met,
        "status": (
            "passed"
            if release_gate_met
            else (
                "failed"
                if errors
                else (
                    "smoke_passed"
                    if not release_eligible
                    else "budget_failed"
                )
            )
        ),
        "artifactShapeValid": not errors,
        "validationErrors": errors,
        "blockers": sorted(set(blockers)),
        "rawArtifact": raw_binding,
        "protocol": deepcopy(protocol),
        "fixture": deepcopy(raw.get("fixture")),
        "environment": deepcopy(raw.get("environment")),
        "summaries": {
            "planRenderLatency": latency_summary(plan_render_values),
            "planFrames": plan_frames,
            "threeFrames": three_frames,
            "picking": latency_summary(pick_values),
            "idleRenderStop": latency_summary(idle_values),
            "assetLoading": _asset_loading_summary(
                samples.get("assetLoading", [])
            ),
            "remountMemoryGrowthPercent": latency_summary(remount_growth),
        },
        "budgetChecks": budgets,
        "network": {
            "externalRequestsBlocked": raw.get("network", {}).get(
                "externalRequestsBlocked"
            ),
            "attemptedExternalRequestCount": len(
                raw.get("network", {}).get(
                    "attemptedExternalRequests",
                    [],
                )
            ),
            "localFailedRequestCount": len(
                raw.get("network", {}).get("localFailedRequests", [])
            ),
        },
    }


def benchmark(
    args: argparse.Namespace,
) -> tuple[dict[str, Any], Path, Path]:
    protocol = protocol_for(args.smoke)
    input_errors = validate_required_inputs(args.edge_path)
    if input_errors:
        raise RuntimeError("; ".join(input_errors))
    layout = json.loads(P4_LAYOUT.read_text(encoding="ascii"))
    fixture_manifest = json.loads(
        BENCHMARK_MANIFEST.read_text(encoding="ascii")
    )
    handler = partial(QuietHandler, directory=str(ROOT))
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f"http://127.0.0.1:{server.server_port}"
    benchmark_url = (
        f"{origin}/tests/fixtures/facility_layout/performance/"
        "facility-layout-release-performance.html"
    )
    recorder = NetworkRecorder(origin)
    started_at = time.time()
    started_utc = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ",
        time.gmtime(started_at),
    )
    errors: list[dict[str, Any]] = []
    unavailable: list[str] = []
    core: dict[str, Any] = {}
    loading: list[dict[str, Any]] = []
    remount: list[dict[str, Any]] = []
    browser_version = None
    browser_headless = (
        True
        if args.headless or args.smoke
        else not args.headed
    )

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                executable_path=str(args.edge_path),
                headless=browser_headless,
                args=[
                    "--enable-precise-memory-info",
                    "--disable-background-timer-throttling",
                    "--disable-renderer-backgrounding",
                    "--disable-backgrounding-occluded-windows",
                ],
            )
            browser_version = browser.version
            try:
                print(
                    "Benchmark phase 1/3: core rendering and interaction",
                    flush=True,
                )
                try:
                    core = run_core_measurements(
                        browser,
                        recorder,
                        benchmark_url,
                        protocol,
                    )
                except Exception as error:  # noqa: BLE001 - evidence capture
                    errors.append(
                        {
                            "phase": "core",
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                    )
                    unavailable.extend(
                        [
                            "full_plan_layers",
                            "three_orbit_pan_select",
                            "picking",
                            "idle_render_stop",
                            "precise_memory",
                        ]
                    )
                print("Benchmark phase 1/3 complete", flush=True)
                print(
                    "Benchmark phase 2/3: progressive asset loading",
                    flush=True,
                )
                try:
                    loading = run_asset_loading(
                        browser,
                        recorder,
                        benchmark_url,
                        protocol,
                    )
                except Exception as error:  # noqa: BLE001 - evidence capture
                    errors.append(
                        {
                            "phase": "asset_loading",
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                    )
                    unavailable.append("progressive_asset_loading")
                print("Benchmark phase 2/3 complete", flush=True)
                print(
                    "Benchmark phase 3/3: suspend/resume memory",
                    flush=True,
                )
                try:
                    remount = run_remount_memory(
                        browser,
                        recorder,
                        benchmark_url,
                        protocol,
                    )
                except Exception as error:  # noqa: BLE001 - evidence capture
                    errors.append(
                        {
                            "phase": "remount_memory",
                            "type": type(error).__name__,
                            "message": str(error),
                        }
                    )
                    unavailable.append("twenty_remount_precise_memory")
                print("Benchmark phase 3/3 complete", flush=True)
            finally:
                browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

    completed_at = time.time()
    source = source_records()
    tracked_status = git_value(
        "status",
        "--porcelain",
        "--untracked-files=no",
    )
    environment = {
        **software_environment(),
        "hostHardware": host_hardware(),
        "browser": {
            "name": "Microsoft Edge",
            "version": browser_version,
            "executable": str(args.edge_path.resolve()),
            "headless": browser_headless,
            "launchArguments": [
                "--enable-precise-memory-info",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-backgrounding-occluded-windows",
            ],
            "runtime": core.get("environment", {}).get("browser"),
            "webgl": core.get("environment", {}).get("webgl"),
        },
    }
    hardware_identity = normalized_hardware_identity(environment)
    environment["hardwareIdentity"] = hardware_identity
    environment["hardwareFingerprintSha256"] = (
        hardware_identity_fingerprint(hardware_identity)
    )
    raw = {
        "schemaVersion": RAW_SCHEMA,
        "benchmarkId": str(uuid.uuid4()),
        "startedAtUtc": started_utc,
        "completedAtUtc": time.strftime(
            "%Y-%m-%dT%H:%M:%SZ",
            time.gmtime(completed_at),
        ),
        "elapsedSeconds": round(completed_at - started_at, 3),
        "benchmarkScope": (
            "Production FacilityLayoutWorkspace with the actual TopPlanAdapter, "
            "FacilitySession, and Three adapter over the P4 full-layer layout "
            "and P5 workspace composition pattern."
        ),
        "protocol": protocol,
        "fixture": {
            "layoutId": layout["layoutId"],
            "displayName": layout["displayName"],
            "schemaVersion": layout["schemaVersion"],
            "placementCount": len(layout["placements"]),
            "zoneCount": len(layout["zones"]),
            "routeCount": len(layout["routes"]),
            "p4DataFixture": P4_LAYOUT.relative_to(ROOT).as_posix(),
            "p5CompositionReference": P5_JS.relative_to(ROOT).as_posix(),
            "referenceHardware": fixture_manifest["referenceHardware"],
            "unsupportedPlanFeatures": {
                "visibleTextLabels": (
                    "Current TopPlanAdapter exposes object labels through "
                    "aria-label rather than SVG text."
                ),
                "placementClearanceVolumes": (
                    "Current TopPlanAdapter renders route corridor widths but "
                    "does not expose per-placement clearance-volume elements."
                ),
            },
        },
        "environment": environment,
        "source": {
            "gitCommit": git_value("rev-parse", "HEAD"),
            "trackedWorktreeDirty": bool(tracked_status),
            "files": source,
        },
        "network": recorder.as_dict(),
        "samples": {
            "core": {
                "mount": core.get("mount"),
                "preciseMemory": core.get("preciseMemory"),
                "finalSnapshot": core.get("finalSnapshot"),
                "destroy": core.get("destroy"),
            },
            "planRender": core.get("planRender", {}),
            "planFrames": core.get("planFrames", []),
            "threeFrames": core.get("threeFrames", []),
            "picking": core.get("picking", {}),
            "idleRenderStop": core.get("idleRenderStop", {}),
            "assetLoading": loading,
            "remountMemory": remount,
        },
        "unavailableRequiredMeasurements": sorted(set(unavailable)),
        "errors": errors,
    }
    output_dir = args.output_dir.resolve()
    raw_path = output_dir / f"{args.artifact_prefix}-raw.json"
    summary_path = output_dir / f"{args.artifact_prefix}-summary.json"
    write_json(raw_path, raw)
    summary = build_summary(raw, raw_path=raw_path)
    write_json(summary_path, summary)
    return summary, raw_path, summary_path


def main() -> int:
    args = parse_args()
    try:
        summary, raw_path, summary_path = benchmark(args)
    except Exception as error:  # noqa: BLE001 - CLI fail-closed boundary
        print(
            f"Facility release benchmark could not start: {error}",
            file=sys.stderr,
            flush=True,
        )
        return 2
    print(f"Wrote raw samples: {raw_path}", flush=True)
    print(f"Wrote summary: {summary_path}", flush=True)
    print(
        "Artifact shape: "
        + ("valid" if summary["artifactShapeValid"] else "invalid"),
        flush=True,
    )
    print(
        "Release gate: "
        + ("met" if summary["releaseGateMet"] else "not met"),
        flush=True,
    )
    if summary["validationErrors"]:
        print(
            "Validation errors: "
            + ", ".join(summary["validationErrors"]),
            file=sys.stderr,
            flush=True,
        )
    if not summary["artifactShapeValid"]:
        return 2
    if summary["releaseEligible"] and not summary["releaseGateMet"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
