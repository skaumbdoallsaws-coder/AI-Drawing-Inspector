"""Playwright smoke test for Compare-viewport Sage highlighting.

Drives the LIVE app at http://127.0.0.1:8020. Reproduces the user's
flow:
    1030034 -> 3D Model -> Compare -> Rev B vs Rev C ->
    apply synthetic compare_features markers ->
    capture before/after screenshots + dump viewer state.

This script is intentionally NOT a pytest test -- it's an
operator-runnable diagnostic. The pytest suite cannot drive a real
browser inside CI.

Outputs:
    runtime_logs/compare_highlight_before.png
    runtime_logs/compare_highlight_after.png
    runtime_logs/compare_highlight_findings.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "runtime_logs"
OUT_DIR.mkdir(parents=True, exist_ok=True)

APP_URL = "http://127.0.0.1:8020/"
PART_NUMBER = "1030034"
REV_A = "B"
REV_B = "C"

# Synthetic markers the user reported Sage emits for this prompt.
COMPARE_MARKERS = [
    "pair_0",                            # whatever the first changed feature is
    "removed_netblend_boundary_surface5",
    "removed_mirrorsolid_mirror7",
]


def run() -> int:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("playwright not installed", file=sys.stderr)
        return 2

    findings: dict = {"url": APP_URL, "part": PART_NUMBER,
                      "revA": REV_A, "revB": REV_B}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1600, "height": 1000})
        page = context.new_page()
        # Surface JS console messages so we can see [Compare] logs.
        page.on("console", lambda msg: print(f"[browser:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda err: print(f"[browser:error] {err}"))

        page.goto(APP_URL, wait_until="networkidle", timeout=30_000)

        # The Compare-tab IIFE keeps state/partDiffState private. We
        # use the window.__compareDbg surface to reach them.
        page.wait_for_function("window.__compareDbg", timeout=15_000)
        seed_result = page.evaluate(f"""
            window.__compareDbg.seedRevisionsAndDiff('{PART_NUMBER}', '{REV_A}', '{REV_B}')
        """)
        findings["seed_result"] = seed_result

        # Now trigger the actual Compare subtab render -- which auto-
        # mounts the viewers within ~50ms.
        page.evaluate("window.__compareDbg.mountCompareSubtab()")
        page.wait_for_function(
            "window.__compareDbg.partDiffState.viewerA"
            " && window.__compareDbg.partDiffState.viewerB"
            " && window.__compareDbg.partDiffState.viewerA.partMeshMap"
            " && window.__compareDbg.partDiffState.viewerB.partMeshMap"
            " && window.__compareDbg.partDiffState.diffResult",
            timeout=30_000,
        )
        page.wait_for_timeout(1500)  # let GLB scene fully populate + render settle

        before_png = OUT_DIR / "compare_highlight_before.png"
        page.screenshot(path=str(before_png), full_page=False)
        findings["before_screenshot"] = str(before_png.relative_to(REPO_ROOT))

        # ── Dump the actual mesh map keys so we can see if they match
        #    the cad_feature_ids the diff reports.
        snapshot = page.evaluate("""
            (function() {
                const dbg = window.__compareDbg;
                const partDiffState = dbg.partDiffState;
                const out = {};
                const viewerA = partDiffState.viewerA;
                const viewerB = partDiffState.viewerB;
                out.partMeshMapKeysA = Object.keys(viewerA && viewerA.partMeshMap || {});
                out.partMeshMapKeysB = Object.keys(viewerB && viewerB.partMeshMap || {});
                const diff = partDiffState.diffResult || {};
                out.changed_feature_keys = Object.keys(diff.changed_features || {});
                out.added_features  = (diff.added_features  || []).map(f => typeof f === 'object' ? f.cad_feature_id : f);
                out.removed_features = (diff.removed_features || []).map(f => typeof f === 'object' ? f.cad_feature_id : f);
                out.modified_features_keys = Object.keys(diff.modified_features || {});
                // bounding box of every mesh in A so we can see scale
                const bboxes = [];
                const box = new THREE.Box3();
                Object.entries(viewerA.partMeshMap).forEach(([k, meshes]) => {
                    meshes.forEach(m => {
                        box.setFromObject(m);
                        if (isFinite(box.min.x) && isFinite(box.max.x)) {
                            bboxes.push({
                                key: k,
                                size: [box.max.x-box.min.x, box.max.y-box.min.y, box.max.z-box.min.z],
                                center: [(box.min.x+box.max.x)/2, (box.min.y+box.max.y)/2, (box.min.z+box.max.z)/2],
                            });
                        }
                    });
                });
                out.bboxes_sample = bboxes.slice(0, 30);
                return out;
            })();
        """)
        findings["snapshot_before_apply"] = snapshot

        # Build per-scene synthetic markers using REAL changed_feature_keys
        # from the diff. We pass the SAME marker set the user reported.
        first_change_key = (snapshot.get("changed_feature_keys") or [None])[0]
        markers = []
        if first_change_key is not None:
            markers.append(f"pair_0")
        # Use real removed names from the diff so the test is reproducible.
        for rid in (snapshot.get("removed_features") or [])[:3]:
            markers.append(f"removed_{rid}")
        findings["applied_markers"] = markers

        # ── Apply the highlights via the existing function. This is
        #    exactly what the Sage tool-call dispatcher does.
        apply_result = page.evaluate("""
            (markers) => {
                try {
                    return window.__compareDbg.applyAgentCompareFeatures(markers);
                } catch (err) {
                    return { ok: false, error: String(err) };
                }
            }
        """, markers)
        findings["apply_result"] = apply_result

        page.wait_for_timeout(600)  # let pulse animate one frame

        after_png = OUT_DIR / "compare_highlight_after.png"
        page.screenshot(path=str(after_png), full_page=False)
        findings["after_screenshot"] = str(after_png.relative_to(REPO_ROOT))

        # ── Verify the emissive intensity actually flipped on the
        #    highlighted meshes (definitive proof the material change
        #    took effect even if the pixels are too small to see).
        post = page.evaluate("""
            (function() {
                const partDiffState = window.__compareDbg.partDiffState;
                const out = {viewerA_highlighted_emissive: [], viewerB_highlighted_emissive: []};
                const collect = (viewer, into) => {
                    if (!viewer || !viewer.partMeshMap) return;
                    Object.entries(viewer.partMeshMap).forEach(([k, meshes]) => {
                        meshes.forEach(m => {
                            const e = m.material && m.material.emissiveIntensity;
                            if (typeof e === 'number' && e > 0.5) {
                                into.push({key: k, intensity: e,
                                           color: m.material.color.getHexString(),
                                           emissive: m.material.emissive.getHexString()});
                            }
                        });
                    });
                };
                collect(partDiffState.viewerA, out.viewerA_highlighted_emissive);
                collect(partDiffState.viewerB, out.viewerB_highlighted_emissive);
                out.viewerA_helpers = (partDiffState.viewerA && partDiffState.viewerA._agentHighlightHelpers || []).length;
                out.viewerB_helpers = (partDiffState.viewerB && partDiffState.viewerB._agentHighlightHelpers || []).length;
                out.cameraA = partDiffState.viewerA && {
                    pos: [partDiffState.viewerA.camera.position.x, partDiffState.viewerA.camera.position.y, partDiffState.viewerA.camera.position.z],
                    target: [partDiffState.viewerA.controls.target.x, partDiffState.viewerA.controls.target.y, partDiffState.viewerA.controls.target.z],
                    fov: partDiffState.viewerA.camera.fov,
                };
                return out;
            })();
        """)
        findings["post_apply_state"] = post

        browser.close()

    findings_path = OUT_DIR / "compare_highlight_findings.json"
    findings_path.write_text(json.dumps(findings, indent=2), encoding="utf-8")
    print(f"\n=== findings written to {findings_path}")
    print(json.dumps({
        "apply_ok": findings.get("apply_result", {}).get("ok"),
        "revAMeshCount": findings.get("apply_result", {}).get("revAMeshCount"),
        "revBMeshCount": findings.get("apply_result", {}).get("revBMeshCount"),
        "before": findings["before_screenshot"],
        "after":  findings["after_screenshot"],
        "viewerA_highlighted_emissive": len(findings.get("post_apply_state", {}).get("viewerA_highlighted_emissive", [])),
        "viewerB_highlighted_emissive": len(findings.get("post_apply_state", {}).get("viewerB_highlighted_emissive", [])),
        "viewerA_helpers": findings.get("post_apply_state", {}).get("viewerA_helpers"),
        "viewerB_helpers": findings.get("post_apply_state", {}).get("viewerB_helpers"),
        "cameraA": findings.get("post_apply_state", {}).get("cameraA"),
        "mesh_map_keys_A_count": len(findings.get("snapshot_before_apply", {}).get("partMeshMapKeysA", [])),
    }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(run())
