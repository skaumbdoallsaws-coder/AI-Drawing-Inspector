from __future__ import annotations

import asyncio
import csv
import json
import re
import argparse
from datetime import datetime
from pathlib import Path

from playwright.async_api import async_playwright


APP_URL = "http://127.0.0.1:8021/"
REPO_ROOT = Path(__file__).resolve().parents[1]
SEMANTIC_PATH = REPO_ROOT / "facility_layout_semantic.json"
SCREENSHOT_ROOT = Path(r"C:\Users\might\OneDrive\Desktop\Screenshots")


def slug(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9]+", "_", value.strip()).strip("_")
    return value[:80] or "route"


def load_endpoints() -> list[dict]:
    semantic = json.loads(SEMANTIC_PATH.read_text(encoding="utf-8"))
    endpoints: list[dict] = []
    for asset in semantic.get("materialHandlingAssets", []):
        endpoints.append(
            {
                "id": asset["id"],
                "label": asset.get("displayName") or asset["id"],
                "kind": "forklift",
            }
        )
    for row in semantic.get("rackRows", []):
        endpoints.append(
            {
                "id": row["id"],
                "label": row.get("displayName") or row["id"],
                "kind": "rack_row",
            }
        )
    return endpoints


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", default="", help="Existing output folder to resume into.")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum new screenshots to capture.")
    args = parser.parse_args()

    endpoints = load_endpoints()
    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_dir = SCREENSHOT_ROOT / f"facility_routes_all_{stamp}"
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.csv"
    manifest_rows = []
    if manifest_path.exists():
        with manifest_path.open("r", newline="", encoding="utf-8") as f:
            manifest_rows = list(csv.DictReader(f))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1440, "height": 960}, device_scale_factor=1)
        page.set_default_timeout(120_000)
        await page.goto(APP_URL, wait_until="domcontentloaded")

        await page.evaluate(
            """
            () => {
                const previousType = trainingState.type;
                trainingState.type = 'facility_layout';
                trainingState.viewportMode = 'facility_layout';
                try { _trainApplyTrainingTypeDefaults(previousType); } catch (_) {}
                switchTab('training');
            }
            """
        )

        await page.wait_for_function(
            """
            () => !!(
                window.THREE
                && state.assyRenderer
                && state.assyLiveScene
                && state.assyCamera
                && state.assyControls
                && trainingState.facilityLayoutData
                && document.querySelector('#assy-3d-container canvas')
            )
            """,
            timeout=180_000,
        )

        await page.evaluate(
            """
            () => {
                if (trainingState.facilityLayoutShowGrid !== true) {
                    trainingState.facilityLayoutShowGrid = true;
                    try { _trainUpdateFacilityLayoutGrid(); } catch (_) {}
                }
                if (typeof _trainClearFacilityRoute === 'function') {
                    try { _trainClearFacilityRoute(); } catch (_) {}
                }
                const fitTop = () => {
                    const box = new THREE.Box3().setFromObject(state.assyLiveScene);
                    const center = new THREE.Vector3();
                    const size = new THREE.Vector3();
                    box.getCenter(center);
                    box.getSize(size);
                    const camera = state.assyCamera;
                    const controls = state.assyControls;
                    const maxPlanDim = Math.max(size.x || 1, size.z || 1);
                    const vFov = Math.max(0.01, camera.fov * Math.PI / 180);
                    const dist = (maxPlanDim / (2 * Math.tan(vFov / 2))) * 1.75;
                    controls.target.copy(center);
                    camera.up.set(0, 0, -1);
                    camera.position.set(center.x, center.y + dist, center.z);
                    camera.near = Math.max(0.01, dist / 100);
                    camera.far = Math.max(1000, dist * 100);
                    camera.lookAt(center);
                    camera.updateProjectionMatrix();
                    try { _syncOrbitFromCamera(controls, camera); } catch (_) {}
                };
                fitTop();
                window.__captureFacilityTopView = fitTop;
            }
            """
        )

        viewport = page.locator("#assy-3d-container")
        await viewport.wait_for(state="visible", timeout=120_000)

        route_index = 1
        captured_this_run = 0
        total = len(endpoints) * (len(endpoints) - 1)
        for start in endpoints:
            for end in endpoints:
                if start["id"] == end["id"]:
                    continue

                safe_name = (
                    f"{route_index:03d}_"
                    f"{slug(start['label'])}_to_{slug(end['label'])}.png"
                )
                screenshot_path = out_dir / safe_name
                if screenshot_path.exists() and screenshot_path.stat().st_size > 0:
                    print(f"[{route_index:03d}/{total}] skip existing {start['label']} -> {end['label']}")
                    route_index += 1
                    continue

                result = await page.evaluate(
                    """
                    async ({ startId, endId }) => {
                        const res = await fetch('/api/training/facility-layout/route', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ start: startId, end: endId }),
                        });
                        const payload = await res.json().catch(() => ({}));
                        if (!res.ok || payload.success === false) {
                            return { ok: false, status: res.status, error: payload.detail || payload.error || 'route failed' };
                        }
                        const route = payload.result || payload;
                        trainingState.facilityLayoutRoute = route;
                        _trainDrawFacilityRoute(route);
                        if (window.__captureFacilityTopView) window.__captureFacilityTopView();
                        return {
                            ok: true,
                            route,
                            distanceMeters: route.distanceMeters,
                            etaText: route.etaText,
                            obstacleCheck: route.method && route.method.obstacleCheck,
                        };
                    }
                    """,
                    {"startId": start["id"], "endId": end["id"]},
                )

                if result.get("ok"):
                    await page.wait_for_timeout(250)
                    await viewport.screenshot(path=str(screenshot_path))
                    captured_this_run += 1
                manifest_rows.append(
                    {
                        "index": route_index,
                        "file": safe_name if result.get("ok") else "",
                        "start_id": start["id"],
                        "start_label": start["label"],
                        "start_kind": start["kind"],
                        "end_id": end["id"],
                        "end_label": end["label"],
                        "end_kind": end["kind"],
                        "ok": result.get("ok"),
                        "distance_m": result.get("distanceMeters"),
                        "eta": result.get("etaText"),
                        "obstacle_check": result.get("obstacleCheck"),
                        "error": result.get("error", ""),
                    }
                )
                print(f"[{route_index:03d}/{total}] {start['label']} -> {end['label']}")
                route_index += 1
                if args.limit and captured_this_run >= args.limit:
                    break
            if args.limit and captured_this_run >= args.limit:
                break

        if manifest_rows:
            deduped = {}
            for row in manifest_rows:
                deduped[str(row["index"])] = row
            manifest_rows = [deduped[k] for k in sorted(deduped, key=lambda x: int(x))]
            with manifest_path.open("w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(manifest_rows[0].keys()))
                writer.writeheader()
                writer.writerows(manifest_rows)

        (out_dir / "endpoints.json").write_text(json.dumps(endpoints, indent=2), encoding="utf-8")
        await browser.close()

    png_count = len(list(out_dir.glob("*.png")))
    print(f"Saved {png_count} screenshots to {out_dir}")


if __name__ == "__main__":
    asyncio.run(main())
