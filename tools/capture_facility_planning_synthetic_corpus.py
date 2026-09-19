"""Capture representative synthetic Facility Planning layouts in the real workspace."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from PIL import Image, ImageStat
from playwright.sync_api import sync_playwright


ROOT = Path(__file__).resolve().parents[1]
CORPUS_ROOT = (
    ROOT / "generated" / "facility_planning" / "synthetic-corpus" / "v1"
)
DEFAULT_OUTPUT = (
    ROOT
    / "tests"
    / "fixtures"
    / "facility_layout"
    / "synthetic_corpus"
    / "browser"
)
DEFAULT_PACKAGE_IDS = (
    "syn-fac-linear-discrete-assembly-balanced-v1",
    "syn-fac-distribution-center-high-throughput-v1",
    "syn-fac-robotic-fabrication-expanded-v1",
    "syn-fac-warehouse-production-hybrid-balanced-v1",
    "syn-fac-laboratory-pilot-plant-balanced-v1",
    "syn-fac-compact-urban-factory-balanced-v1",
)
DEFAULT_THREE_PACKAGE_IDS = {
    "syn-fac-robotic-fabrication-expanded-v1",
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def _slug(value: str) -> str:
    return "".join(
        character if character.isalnum() else "-" for character in value
    ).strip("-")


def _image_evidence(path: Path) -> dict[str, Any]:
    image = Image.open(path).convert("RGB")
    statistics = ImageStat.Stat(image)
    spread = sum(max(channel) - min(channel) for channel in image.getextrema())
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "width": image.width,
        "height": image.height,
        "byteLength": path.stat().st_size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "channelMean": [round(value, 3) for value in statistics.mean],
        "nonBlank": spread > 24 and path.stat().st_size > 20_000,
    }


def _canvas_pixel_evidence(page, page_path: Path) -> dict[str, Any]:
    bounds = page.locator("#ip-flw-three-view canvas").bounding_box()
    if not bounds:
        raise AssertionError("Facility 3D canvas has no browser bounds")
    page_image = Image.open(page_path).convert("RGB")
    left = max(0, int(round(bounds["x"])))
    top = max(0, int(round(bounds["y"])))
    right = min(page_image.width, int(round(bounds["x"] + bounds["width"])))
    bottom = min(page_image.height, int(round(bounds["y"] + bounds["height"])))
    canvas = page_image.crop((left, top, right, bottom))
    pixels = list(canvas.getdata())
    corners = (
        pixels[0],
        pixels[canvas.width - 1],
        pixels[(canvas.height - 1) * canvas.width],
        pixels[-1],
    )
    background = max(set(corners), key=corners.count)
    changed = 0
    maximum_delta = 0
    for red, green, blue in pixels:
        delta = (
            abs(red - background[0])
            + abs(green - background[1])
            + abs(blue - background[2])
        )
        maximum_delta = max(maximum_delta, delta)
        if delta > 24:
            changed += 1
    canvas_path = page_path.with_name(
        page_path.stem.replace("-3d", "-3d-canvas") + page_path.suffix
    )
    canvas.save(canvas_path)
    return {
        "path": canvas_path.relative_to(ROOT).as_posix(),
        "width": canvas.width,
        "height": canvas.height,
        "backgroundRgb": list(background),
        "changedPixelCount": changed,
        "changedPixelFraction": round(
            changed / max(1, canvas.width * canvas.height), 8
        ),
        "maximumDelta": maximum_delta,
        "nonBlank": changed >= 1_000 and maximum_delta >= 40,
        "sha256": hashlib.sha256(canvas_path.read_bytes()).hexdigest(),
    }


def _open_facility(page, app_url: str) -> None:
    page.goto(app_url, wait_until="load", timeout=120_000)
    page.wait_for_function(
        """() => (
            window.__inspectorProMainScriptReady === true
            && typeof switchTab === 'function'
            && typeof _trainApplyTrainingTypeDefaults === 'function'
        )""",
        timeout=120_000,
    )
    page.evaluate(
        """() => {
            const previous = trainingState.type;
            trainingState.type = 'facility_layout';
            trainingState.viewportMode = 'facility_layout';
            _trainApplyTrainingTypeDefaults(previous);
            switchTab('training');
        }"""
    )
    page.wait_for_selector(
        "#trainFacilityLayoutAuthoring.ip-flw-root",
        state="visible",
        timeout=120_000,
    )
    page.wait_for_function(
        """() => !!(
            window._trainFacilityLayoutAuthoringApp
            && _trainFacilityLayoutAuthoringApp.workspace
            && !_trainFacilityLayoutAuthoringApp.session.getState().busy
        )""",
        timeout=120_000,
    )


def _saved_layout(page) -> dict[str, Any]:
    return page.evaluate(
        """async () => {
            const response = await fetch('/api/facility-layouts/site-local/fl-main');
            if (!response.ok) throw new Error(`saved layout ${response.status}`);
            return await response.json();
        }"""
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--url",
        default=os.environ.get("APP_URL", "http://127.0.0.1:8141/"),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--package-id", action="append", dest="package_ids")
    args = parser.parse_args()

    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((CORPUS_ROOT / "manifest.json").read_text(encoding="utf-8"))
    records = {item["packageId"]: item for item in manifest["examples"]}
    package_ids = tuple(args.package_ids or DEFAULT_PACKAGE_IDS)
    unknown = [package_id for package_id in package_ids if package_id not in records]
    if unknown:
        raise ValueError(f"Unknown synthetic package IDs: {unknown}")

    page_errors: list[str] = []
    console_errors: list[str] = []
    failed_requests: list[str] = []
    server_errors: list[str] = []
    captures = []

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--enable-unsafe-swiftshader"],
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            device_scale_factor=1,
            service_workers="block",
        )
        context.add_init_script(
            "localStorage.setItem('inspectorpro.theme', 'light');"
        )
        page = context.new_page()
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.on(
            "console",
            lambda message: console_errors.append(message.text)
            if message.type == "error"
            else None,
        )
        page.on(
            "requestfailed",
            lambda request: failed_requests.append(
                f"{request.method} {request.url}: {request.failure}"
            ),
        )
        page.on(
            "response",
            lambda response: server_errors.append(
                f"{response.status} {response.url}"
            )
            if response.status >= 500
            else None,
        )

        _open_facility(page, args.url)
        saved_before = _saved_layout(page)
        saved_before_bytes = _canonical_bytes(saved_before)

        for index, package_id in enumerate(package_ids, start=1):
            record = records[package_id]
            layout = json.loads(
                (CORPUS_ROOT / record["layoutPath"]).read_text(encoding="utf-8")
            )
            state = page.evaluate(
                """value => {
                    const app = window._trainFacilityLayoutAuthoringApp;
                    app.session.load({
                        layout: value.layout,
                        revision: value.revision,
                    });
                    app.workspace.executeCommand('fit');
                    const current = app.session.getState();
                    return {
                        dirty: current.dirty,
                        zones: (current.layout.zones || []).length,
                        routes: (current.layout.routes || []).length,
                        placements: (current.layout.placements || []).length,
                        floorMarkings: (current.layout.floorMarkings || []).length,
                    };
                }""",
                {"layout": layout, "revision": record["layoutRevision"]},
            )
            page.wait_for_timeout(1_200)
            filename = f"{index:02d}-{_slug(package_id)}.png"
            screenshot_path = output / filename
            page.locator("#trainFacilityLayoutAuthoring").screenshot(
                path=str(screenshot_path)
            )
            image = _image_evidence(screenshot_path)
            if not image["nonBlank"]:
                raise AssertionError(f"Blank synthetic corpus capture: {package_id}")
            if state != {
                "dirty": False,
                "zones": record["counts"]["zones"],
                "routes": record["counts"]["routes"],
                "placements": record["counts"]["placements"],
                "floorMarkings": record["counts"]["floorMarkings"],
            }:
                raise AssertionError(
                    f"Browser state differs from manifest for {package_id}: {state}"
                )
            capture = {
                "packageId": package_id,
                "archetypeId": record["archetypeId"],
                "variantId": record["variantId"],
                "split": record["split"],
                "layoutRevision": record["layoutRevision"],
                "counts": record["counts"],
                "browserState": state,
                "planImage": image,
                "threeDImage": None,
            }
            if package_id in DEFAULT_THREE_PACKAGE_IDS:
                page.evaluate(
                    """() => document.querySelector(
                        '.ip-flw-view-tab[data-view="3d"]'
                    ).click()"""
                )
                page.wait_for_function(
                    """() => {
                        const root = document.querySelector(
                            '#trainFacilityLayoutAuthoring'
                        );
                        const canvas = document.querySelector(
                            '#ip-flw-three-view canvas'
                        );
                        return !!(
                            root
                            && root.getAttribute('data-view-mode') === '3d'
                            && canvas
                            && canvas.width > 0
                            && canvas.height > 0
                        );
                    }""",
                    timeout=30_000,
                )
                page.wait_for_timeout(1_500)
                three_path = output / f"{index:02d}-{_slug(package_id)}-3d.png"
                page.screenshot(path=str(three_path))
                capture["threeDImage"] = _image_evidence(three_path)
                capture["threeDCanvas"] = _canvas_pixel_evidence(
                    page, three_path
                )
                if not capture["threeDImage"]["nonBlank"]:
                    raise AssertionError(
                        f"Blank synthetic 3D corpus capture: {package_id}"
                    )
                if not capture["threeDCanvas"]["nonBlank"]:
                    raise AssertionError(
                        f"Blank synthetic 3D canvas: {package_id}"
                    )
                page.evaluate(
                    """() => document.querySelector(
                        '.ip-flw-view-tab[data-view="plan"]'
                    ).click()"""
                )
                page.wait_for_timeout(250)
            captures.append(capture)

        saved_after = _saved_layout(page)
        saved_unchanged = _canonical_bytes(saved_after) == saved_before_bytes
        browser.close()

    evidence = {
        "schemaVersion": "facility-planning-synthetic-browser-evidence-v1",
        "corpusId": manifest["corpusId"],
        "corpusRevision": manifest["corpusRevision"],
        "appUrl": args.url,
        "authority": manifest["authority"],
        "captureCount": len(captures),
        "captures": captures,
        "savedLayoutUnchanged": saved_unchanged,
        "pageErrors": page_errors,
        "consoleErrors": console_errors,
        "failedRequests": failed_requests,
        "serverErrors": server_errors,
    }
    if not saved_unchanged:
        raise AssertionError("Synthetic captures changed the saved Facility Layout")
    if page_errors or console_errors or failed_requests or server_errors:
        raise AssertionError(
            "Browser errors occurred during synthetic corpus capture: "
            + json.dumps(
                {
                    "pageErrors": page_errors,
                    "consoleErrors": console_errors,
                    "failedRequests": failed_requests,
                    "serverErrors": server_errors,
                },
                sort_keys=True,
            )
        )
    evidence_path = output.parent / "browser-evidence.json"
    evidence_path.write_text(
        json.dumps(evidence, indent=2, sort_keys=True, ensure_ascii=True) + "\n",
        encoding="utf-8",
    )
    print(evidence_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
