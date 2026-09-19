"""Live browser proof that FAI viewport actions preserve neutral-gray materials.

This smoke drives the same registered browser functions used by Sage without
calling an LLM provider. It covers the two demo transitions:

1. Show the affected components in motion.
2. Bring the crankshaft into the running highlighted set.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)
APP_URL = os.environ.get("SMOKE_APP_URL", "http://127.0.0.1:8125/")
PART_NUMBER = os.environ.get("SMOKE_PART_NUMBER", "100006")
THREE_URL = "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
THREE_CACHE = OUT_DIR / "three.r128.min.js"


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    report: dict[str, object] = {
        "url": APP_URL,
        "part": PART_NUMBER,
        "checks": {},
    }

    def check(name: str, ok: bool, detail=None) -> None:
        report["checks"][name] = {"ok": bool(ok), "detail": detail}
        suffix = f" :: {detail}" if detail is not None and not ok else ""
        print(f"{'PASS' if ok else 'FAIL'} {name}{suffix}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1600, "height": 1000},
            service_workers="block",
        )
        page = context.new_page()
        if THREE_CACHE.exists():
            page.route(
                THREE_URL,
                lambda route: route.fulfill(
                    status=200,
                    content_type="application/javascript",
                    body=THREE_CACHE.read_text(encoding="utf-8"),
                ),
            )
        page.on("pageerror", lambda error: print(f"[browser:error] {error}"))
        page.goto(APP_URL, wait_until="networkidle", timeout=60_000)
        page.wait_for_function(
            "Boolean(window.__compareDbg)"
            " && typeof window.__compareDbg.highlightAssemblyParts === 'function'",
            timeout=30_000,
        )

        page.fill("#partSearch", PART_NUMBER)
        page.dispatch_event("#partSearch", "input")
        page.wait_for_timeout(600)
        page.locator(f".search-dropdown-item:has-text('{PART_NUMBER}')").first.click()
        page.wait_for_function(
            f"window.__compareDbg.state.partNumber === '{PART_NUMBER}'",
            timeout=30_000,
        )
        page.click(".tab[data-tab='assembly']")
        page.wait_for_function(
            "window.__compareDbg.state.activeTab === 'assembly'"
            " && window.__compareDbg.state.assyLiveScene"
            " && window.__compareDbg.state.assyPartMeshMap"
            " && window.__compareDbg.state.motionPkgInfo"
            " && window.__compareDbg.state.motionPkgInfo.summary",
            timeout=45_000,
        )

        fixture = page.evaluate(
            """
            () => {
                const s = window.__compareDbg.state;
                const motions = s.motionPkgInfo.summary.available_motions || [];
                const motion = motions[0] || null;
                const groups = motion && motion.groups || [];
                const affected = groups.find(group =>
                    /affected|fai|pin/i.test(`${group.id || ''} ${group.label || ''}`)
                    && (group.part_numbers || []).length > 1
                ) || groups.find(group => (group.part_numbers || []).includes('100006'));
                const crank = groups.find(group =>
                    /crank/i.test(`${group.id || ''} ${group.label || ''}`)
                    && (group.part_numbers || []).length === 1
                );
                return {
                    motion_id: motion && motion.motion_id,
                    affected_parts: affected && affected.part_numbers || [],
                    crank_part: crank && String(crank.part_numbers[0]),
                };
            }
            """
        )
        check("fixture_has_motion", bool(fixture.get("motion_id")), fixture)
        check("fixture_has_affected_group", len(fixture.get("affected_parts") or []) > 1, fixture)
        check("fixture_has_crankshaft", bool(fixture.get("crank_part")), fixture)
        if not all(
            (
                fixture.get("motion_id"),
                fixture.get("affected_parts"),
                fixture.get("crank_part"),
            )
        ):
            browser.close()
            return 1

        def material_snapshot() -> dict:
            return page.evaluate(
                """
                () => {
                    const s = window.__compareDbg.state;
                    const selected = Array.from(s.partExplorerAgentParts || []);
                    const selectedMeshes = new Set();
                    selected.forEach(pn => (s.assyPartMeshMap[pn] || []).forEach(mesh => selectedMeshes.add(mesh)));
                    const neutral = [0xae / 255, 0xb5 / 255, 0xbb / 255];
                    const rows = [];
                    selectedMeshes.forEach(mesh => {
                        if (!mesh.visible) return;
                        const materials = Array.isArray(mesh.material) ? mesh.material : [mesh.material];
                        materials.filter(Boolean).forEach(material => {
                            const color = material.color
                                ? [material.color.r, material.color.g, material.color.b] : null;
                            const emissive = material.emissive
                                ? [material.emissive.r, material.emissive.g, material.emissive.b] : null;
                            const spread = values => values
                                ? Math.max(...values) - Math.min(...values) : 0;
                            const neutralDelta = color
                                ? Math.max(...color.map((value, index) => Math.abs(value - neutral[index])))
                                : 0;
                            rows.push({
                                name: mesh.name || '',
                                color,
                                emissive,
                                color_spread: spread(color),
                                neutral_delta: neutralDelta,
                                emissive_spread: spread(emissive),
                                emissive_intensity: Number(material.emissiveIntensity || 0),
                                has_map: !!material.map,
                                vertex_colors: !!material.vertexColors,
                            });
                        });
                    });
                    return {
                        appearance_mode: s.assyAppearanceMode,
                        selected,
                        motion_playing: !!s.motionPlaying,
                        rows,
                        all_neutral: rows.length > 0 && rows.every(row =>
                            row.neutral_delta < 0.002 && row.emissive_spread < 0.002
                            && !row.has_map && !row.vertex_colors
                        ),
                    };
                }
                """
            )

        started = page.evaluate(
            """
            fixture => {
                const dbg = window.__compareDbg;
                dbg.highlightAssemblyParts(fixture.affected_parts, {mode: 'replace'});
                return dbg.playAssemblyMotion({motion_id: fixture.motion_id, rpm: 30, loop: true});
            }
            """,
            fixture,
        )
        check("affected_motion_started", bool(started.get("ok")), started)
        page.wait_for_function("window.__compareDbg.state.motionPlaying === true", timeout=20_000)
        page.wait_for_timeout(700)
        affected = material_snapshot()
        check("affected_motion_uses_neutral_mode", affected["appearance_mode"] == "neutral", affected)
        check("affected_motion_materials_use_neutral_palette", affected["all_neutral"], affected)
        page.screenshot(
            path=str(OUT_DIR / "fai_neutral_affected_motion.png"),
            full_page=False,
        )

        page.evaluate(
            "fixture => window.__compareDbg.highlightAssemblyParts([fixture.crank_part], {mode: 'add'})",
            fixture,
        )
        page.wait_for_timeout(500)
        with_crank = material_snapshot()
        check("crankshaft_added", fixture["crank_part"] in with_crank["selected"], with_crank)
        check("motion_continues_after_crankshaft_add", with_crank["motion_playing"], with_crank)
        check("crankshaft_view_materials_use_neutral_palette", with_crank["all_neutral"], with_crank)
        page.screenshot(
            path=str(OUT_DIR / "fai_neutral_with_crankshaft.png"),
            full_page=False,
        )

        page.evaluate("window.__compareDbg.stopAssemblyMotion()")
        browser.close()

    output = OUT_DIR / "fai_neutral_materials_smoke.json"
    output.write_text(json.dumps(report, indent=2, ensure_ascii=True) + "\n", encoding="ascii")
    failed = [name for name, row in report["checks"].items() if not row["ok"]]
    print(f"findings -> {output.relative_to(ROOT)}")
    print(f"{len(report['checks']) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(run())
