"""Live Playwright smoke for root Assembly viewport state persistence.

The test avoids the agent provider entirely. It drives the same browser actions
that the tools use, then verifies a fresh Three.js scene is rehydrated with the
saved semantic state after an Assembly -> Drawing -> Assembly round trip.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8021/")
PART_NUMBER = os.environ.get("SMOKE_PART_NUMBER", "100006")
THREE_CDN_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = OUT_DIR / "three.r128.min.js"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {"url": APP_URL, "part": PART_NUMBER, "checks": {}}

    def record(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        suffix = f" :: {detail}" if detail is not None and not ok else ""
        print(f"{'PASS' if ok else 'FAIL'} {name}{suffix}")

    def vector_distance(left, right) -> float:
        if not isinstance(left, list) or not isinstance(right, list) or len(left) != len(right):
            return float("inf")
        return sum((float(a) - float(b)) ** 2 for a, b in zip(left, right)) ** 0.5

    three_js = None
    try:
        if THREE_CACHE.exists() and THREE_CACHE.stat().st_size > 100_000:
            three_js = THREE_CACHE.read_text(encoding="utf-8")
        else:
            with urllib.request.urlopen(THREE_CDN_URL, timeout=15) as response:
                three_js = response.read().decode("utf-8")
            THREE_CACHE.write_text(three_js, encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        print(f"[smoke:warn] Three.js route unavailable: {exc}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        if three_js:
            page.route(
                THREE_CDN_URL,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/javascript",
                    body=three_js,
                ),
            )
        page.on("pageerror", lambda error: print(f"[browser:error] {error}"))
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function("window.__compareDbg && window.__compareDbg.assemblyViewportSnapshot", timeout=30_000)

        page.fill("#partSearch", PART_NUMBER)
        page.dispatch_event("#partSearch", "input")
        page.wait_for_timeout(500)
        page.locator(f".search-dropdown-item:has-text('{PART_NUMBER}')").first.click()
        page.wait_for_function(
            f"window.__compareDbg.state.partNumber === '{PART_NUMBER}'", timeout=30_000
        )

        page.click(".tab[data-tab='assembly']")
        page.wait_for_function(
            "window.__compareDbg.state.activeTab === 'assembly'"
            " && window.__compareDbg.state.assyLiveScene"
            " && window.__compareDbg.state.assyPartMeshMap",
            timeout=45_000,
        )
        page.wait_for_function(
            "window.__compareDbg.state.motionPkgInfo"
            " && window.__compareDbg.state.motionPkgInfo.summary",
            timeout=45_000,
        )

        fixture = page.evaluate(
            """
            async () => {
                const s = window.__compareDbg.state;
                const contextResponse = await fetch('/api/assembly-context/' + encodeURIComponent(s.partNumber));
                const context = contextResponse.ok ? await contextResponse.json() : {};
                const rows = context.part_color_legend || [];
                const find = (rx) => rows.find(row => rx.test(String(row.description || row.part_name || row.old_key || '')));
                const lower = find(/lower.*(block|housing)|engine.*block/i);
                const crank = find(/crank/i);
                const motion = ((s.motionPkgInfo.summary.available_motions || [])[0]) || null;
                return {
                    piston: String(s.partNumber),
                    lower: lower ? String(lower.part_number) : null,
                    crank: crank ? String(crank.part_number) : null,
                    motion_id: motion && motion.motion_id,
                    feature: s.profileData && Array.isArray(s.profileData.features) ? s.profileData.features[0] : null,
                };
            }
            """
        )
        record("fixture_has_motion", bool(fixture.get("motion_id")), fixture)
        record(
            "fixture_has_distinct_parts",
            bool(fixture.get("piston") and fixture.get("lower") and fixture.get("crank")),
            fixture,
        )
        if not fixture.get("motion_id") or not fixture.get("lower") or not fixture.get("crank"):
            browser.close()
            return 1

        setup = page.evaluate(
            """
            (fixture) => {
                const dbg = window.__compareDbg;
                const s = dbg.state;
                window.__persistenceFixture = fixture;
                dbg.highlightAssemblyParts([fixture.piston], { mode: 'replace' });
                dbg.highlightAssemblyParts([fixture.crank], { mode: 'add' });
                dbg.setAssemblyDisplayOverride(fixture.lower, { hidden: true });
                dbg.setAssemblyDisplayOverride(fixture.crank, { opacity: 0.35 });
                if (fixture.feature) {
                    dbg.setAssemblyFeatureSelection(fixture.piston, fixture.feature, 'persistence-smoke-feature', true);
                }
                s._assyAutoRotate = false;
                return dbg.playAssemblyMotion({ motion_id: fixture.motion_id, rpm: 30, loop: true });
            }
            """,
            fixture,
        )
        record("motion_started", bool(setup.get("ok")), setup)
        page.wait_for_function("window.__compareDbg.state.motionPlaying === true", timeout=20_000)
        page.wait_for_timeout(600)
        before_leave = page.evaluate("window.__compareDbg.assemblyViewportSnapshot()")
        page.screenshot(path=str(OUT_DIR / "assembly_state_persistence_before_leave.png"), full_page=False)

        page.click(".tab[data-tab='drawing']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'drawing'", timeout=15_000)
        suspended = page.evaluate("window.__compareDbg.assemblyViewportSnapshot()")
        page.wait_for_timeout(700)
        suspended_later = page.evaluate("window.__compareDbg.assemblyViewportSnapshot()")
        saved_angle = float((suspended.get("motion_resume") or {}).get("angleDeg") or 0)
        motion_delta_after_leave = abs(float(suspended_later.get("motion_angle_deg") or 0) - float(suspended.get("motion_angle_deg") or 0))
        record(
            "motion_suspended_before_scene_disposal",
            not suspended.get("motion_playing")
            and not suspended.get("motion_package_mode")
            and bool(suspended.get("motion_resume")),
            suspended,
        )
        record(
            "motion_angle_does_not_advance_while_away",
            motion_delta_after_leave < 0.01,
            {"delta_deg": motion_delta_after_leave, "snapshot": suspended_later},
        )
        record(
            "motion_checkpoint_captures_nonrest_pose",
            bool((suspended.get("motion_resume") or {}).get("kind") == "package")
            and abs(saved_angle) > 1.0,
            {"before_leave": before_leave, "suspended": suspended},
        )

        page.click(".tab[data-tab='assembly']")
        page.wait_for_function(
            "window.__compareDbg.state.activeTab === 'assembly'"
            " && window.__compareDbg.state.assyLiveScene"
            " && window.__compareDbg.state.motionPkgMode"
            " && window.__compareDbg.state.motionPlaying",
            timeout=45_000,
        )
        resumed = page.evaluate(
            """
            () => {
                const dbg = window.__compareDbg;
                dbg.pauseAssemblyMotion();
                const s = dbg.state;
                const part = (pn) => (s.assyPartMeshMap[pn] || [])[0] || null;
                const lower = part(window.__persistenceFixture.lower);
                const crank = part(window.__persistenceFixture.crank);
                const group = s.assySemanticFeatureOverlayGroup;
                const hosts = Array.isArray(group && group.userData && group.userData.hostMeshes)
                    ? group.userData.hostMeshes : [];
                const currentSceneHosts = hosts.every(mesh => {
                    let node = mesh;
                    while (node) {
                        if (node === s.assyLiveScene) return true;
                        node = node.parent;
                    }
                    return false;
                });
                return {
                    snapshot: dbg.assemblyViewportSnapshot(),
                    lower_visible: lower ? lower.visible : null,
                    crank_opacity: crank && crank.material ? crank.material.opacity : null,
                    overlay_host_count: hosts.length,
                    overlay_hosts_belong_to_current_scene: currentSceneHosts,
                    camera: s.assyCamera ? s.assyCamera.position.toArray() : null,
                };
            }
            """
        )
        record(
            "motion_rebound_to_new_scene_at_saved_angle",
            resumed["snapshot"]["motion_package_mode"]
            and not resumed["snapshot"]["motion_playing"]
            and resumed["snapshot"].get("last_motion_restore", {}).get("kind") == "package"
            and abs(float(resumed["snapshot"]["last_motion_restore"]["savedAngleDeg"]) - saved_angle) < 0.01
            and abs(
                float(resumed["snapshot"]["last_motion_restore"]["appliedAngleDeg"])
                - saved_angle
            ) < 0.01
            and resumed["snapshot"]["motion_resume"] is None,
            {"saved_angle": saved_angle, "resumed": resumed},
        )
        record(
            "display_overrides_reapplied_to_current_meshes",
            resumed["lower_visible"] is False
            and abs(float(resumed["crank_opacity"] or 0) - 0.35) < 0.05,
            resumed,
        )
        record(
            "part_selection_survived_round_trip",
            set([fixture["piston"], fixture["crank"]]).issubset(
                set(resumed["snapshot"]["selected_parts"])
            ),
            resumed["snapshot"],
        )
        record(
            "camera_pose_survived_round_trip",
            vector_distance(before_leave.get("camera_position"), resumed["snapshot"].get("camera_position")) < 0.001
            and vector_distance(before_leave.get("camera_target"), resumed["snapshot"].get("camera_target")) < 0.001,
            {
                "before": {
                    "position": before_leave.get("camera_position"),
                    "target": before_leave.get("camera_target"),
                },
                "after": {
                    "position": resumed["snapshot"].get("camera_position"),
                    "target": resumed["snapshot"].get("camera_target"),
                },
            },
        )
        if fixture.get("feature"):
            record(
                "semantic_feature_overlay_rebuilt_on_current_scene",
                resumed["overlay_host_count"] > 0 and resumed["overlay_hosts_belong_to_current_scene"],
                resumed,
            )

        page.evaluate("() => { window.__compareDbg.stopAssemblyMotion(); window.__compareDbg.state._assyAutoRotate = true; }")
        page.click(".tab[data-tab='drawing']")
        page.wait_for_function("window.__compareDbg.state.activeTab === 'drawing'", timeout=15_000)
        page.click(".tab[data-tab='assembly']")
        page.wait_for_function(
            "window.__compareDbg.state.activeTab === 'assembly'"
            " && window.__compareDbg.state.assyLiveScene",
            timeout=45_000,
        )
        stopped_after_round_trip = page.evaluate("window.__compareDbg.assemblyViewportSnapshot()")
        record(
            "explicit_stop_does_not_resume_after_tab_change",
            not stopped_after_round_trip["motion_playing"]
            and not stopped_after_round_trip["motion_package_mode"]
            and stopped_after_round_trip["motion_resume"] is None,
            stopped_after_round_trip,
        )
        record(
            "auto_rotate_state_and_control_survive_round_trip",
            stopped_after_round_trip["auto_rotate"] is True
            and page.is_checked("#assy-autorotate"),
            stopped_after_round_trip,
        )

        page.screenshot(path=str(OUT_DIR / "assembly_state_persistence_smoke.png"), full_page=False)
        browser.close()

    output = OUT_DIR / "assembly_state_persistence_smoke.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    failed = [name for name, result in report["checks"].items() if not result["ok"]]
    print(f"findings -> {output.relative_to(REPO_ROOT)}")
    print(f"{len(report['checks']) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
