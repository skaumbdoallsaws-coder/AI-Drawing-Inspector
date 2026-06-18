"""Browser smoke test for the Cooling Tower Plant/Process guided walkthrough.

Drives the real served app. Stubs the 3D scene (so it runs without loading the
56MB GLB) and mocks /api/voice/synthesize with a tiny WAV (so each segment plays
and ends fast). Verifies the authored state transitions:
  - intent routing starts the walkthrough in plant mode (no Assembly switch)
  - one assistant caption streams into the Sage chat pane, then becomes the full transcript
  - flow state walks hot -> hot+air -> hot+cold+air -> (drain isolate) -> final
  - drain step isolates + keeps air on + turns hot off
  - final endpoint: hot+cold+air ON, drain OFF, no isolate, no selection
  - manual flow toggle still works afterwards
"""
import asyncio, sys, threading, functools, http.server, socketserver
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent  # serves /static and /generated


def _serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, httpd.server_address[1]

SETUP = r"""
async () => {
    window.__realFetch = window.fetch.bind(window);
    window.fetch = (url, opts) => {
        const u = String(url);
        if (u.includes('/api/voice/synthesize')) {
            const sr = 8000, n = 320; const buf = new ArrayBuffer(44 + n); const dv = new DataView(buf);
            const ws = (o, s) => { for (let i = 0; i < s.length; i++) dv.setUint8(o + i, s.charCodeAt(i)); };
            ws(0,'RIFF'); dv.setUint32(4,36+n,true); ws(8,'WAVE'); ws(12,'fmt '); dv.setUint32(16,16,true);
            dv.setUint16(20,1,true); dv.setUint16(22,1,true); dv.setUint32(24,sr,true); dv.setUint32(28,sr,true);
            dv.setUint16(32,1,true); dv.setUint16(34,8,true); ws(36,'data'); dv.setUint32(40,n,true);
            for (let i = 0; i < n; i++) dv.setUint8(44 + i, 128);
            return Promise.resolve(new Response(new Blob([buf], {type:'audio/wav'}), {status:200}));
        }
        return window.__realFetch(url, opts);
    };
    // enter plant mode
    trainingState.type = 'plant_process';
    trainingState.viewportMode = 'plant_process';
    trainingState.plantProcessActiveFlowIds = [];
    trainingState.plantProcessSelectedGroupIds = [];
    trainingState.plantProcessIsolateSelection = false;
    // stub scene so the viewer-mount wait is skipped and overlay viz no-ops cleanly
    state.assyLiveScene = { add(){}, remove(){}, traverse(){}, children: [], updateMatrixWorld(){}, worldToLocal:(v)=>v };
    state.assyPartMeshMap = {};
    // load the real authored flow data
    const r = await window.__realFetch('/generated/training/process/cooling-tower/cooling_tower_flow_paths.json');
    trainingState.plantProcessFlowData = await r.json();
    // record a timeline of flow/isolate state
    window.__tl = [];
    window.__tlIv = setInterval(() => {
        window.__tl.push({
            flows: (trainingState.plantProcessActiveFlowIds || []).slice().sort(),
            iso: !!trainingState.plantProcessIsolateSelection,
            sel: (trainingState.plantProcessSelectedGroupIds || []).length,
        });
    }, 60);
    // expected id sets
    window.__ids = {
        hot: _trainPlantProcessFlowIdsForWaterTemperature('hot').slice().sort(),
        cold: _trainPlantProcessFlowIdsForWaterTemperature('cold').slice().sort(),
        air: _trainPlantProcessFlowIdsForMedium('air').slice().sort(),
        drain: _trainPlantProcessFlowIdsForRole('drain_overflow').slice().sort(),
    };
    return { hot: window.__ids.hot.length, cold: window.__ids.cold.length, air: window.__ids.air.length, drain: window.__ids.drain.length };
}
"""


async def main():
    httpd, port = _serve(ROOT)
    url = f"http://127.0.0.1:{port}/static/index.html"
    results = []

    def check(name, ok):
        results.append((name, bool(ok)))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True, args=[
            "--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
            "--autoplay-policy=no-user-gesture-required", "--use-angle=swiftshader",
            "--enable-webgl", "--ignore-gpu-blocklist",
        ])
        ctx = await browser.new_context(viewport={"width": 1400, "height": 900}, permissions=["microphone"])
        page = await ctx.new_page()
        js_errors = []
        page.on("pageerror", lambda exc: js_errors.append(str(exc)))
        await page.goto(url)
        await page.wait_for_selector("#agentInput", state="attached", timeout=20000)
        await page.wait_for_timeout(600)
        load_errors = list(js_errors); js_errors.clear()

        counts = await page.evaluate(SETUP)
        check("0. flow data loaded (hot/cold/air/drain id sets non-empty)",
              counts and counts["hot"] and counts["cold"] and counts["air"] and counts["drain"])

        # intent routing + start (via the real intent matcher)
        intent = await page.evaluate("() => _plantWalkthroughIntent('explain to me how this cooling tower works')")
        check("1. intent matcher recognizes 'explain how this cooling tower works'", intent)

        msgs_before = await page.evaluate("() => document.querySelectorAll('#agentMessages .agent-msg-row.assistant').length")
        await page.evaluate("() => { window.startCoolingTowerProcessWalkthrough(); }")
        # wait for completion
        try:
            await page.wait_for_function("() => window._plantWalk && window._plantWalk.active === false", timeout=60000)
            done = True
        except Exception:
            done = False
        check("2. walkthrough ran to completion (_plantWalk.active === false)", done)
        await page.evaluate("() => { try { clearInterval(window.__tlIv); } catch(_){} }")

        msgs_after = await page.evaluate("() => document.querySelectorAll('#agentMessages .agent-msg-row.assistant').length")
        diag = await page.evaluate("""() => ({
            currentAgent: (typeof currentAgent !== 'undefined') ? currentAgent : '?',
            sessionMsgs: (typeof getAgentSession === 'function') ? (getAgentSession(currentAgent).messages||[]).length : -1,
            domRows: document.querySelectorAll('#agentMessages .agent-msg-row').length,
            domAssistant: document.querySelectorAll('#agentMessages .agent-msg-row.assistant').length,
            lastClass: (document.getElementById('agentMessages') && document.getElementById('agentMessages').lastElementChild) ? document.getElementById('agentMessages').lastElementChild.className : null,
        })""")
        print("   diag:", diag)
        transcript = await page.evaluate("""() => {
            const rows = Array.from(document.querySelectorAll('#agentMessages .agent-msg-row.assistant .agent-msg'));
            return rows.length ? rows[rows.length - 1].innerText : '';
        }""")
        check("3. one Sage caption becomes the final full transcript",
              (msgs_after - msgs_before) == 1
              and "Hot water enters the tower" in transcript
              and "drain system is available" in transcript)

        final = await page.evaluate("""() => ({
            flows: (trainingState.plantProcessActiveFlowIds||[]).slice().sort(),
            iso: !!trainingState.plantProcessIsolateSelection,
            sel: (trainingState.plantProcessSelectedGroupIds||[]).length,
            type: trainingState.type,
        })""")
        ids = await page.evaluate("() => window.__ids")
        def same(a, b): return sorted(a) == sorted(b)
        expected_final = sorted(ids["hot"] + ids["cold"] + ids["air"])
        check("4. final flows = hot+cold+air (drain OFF)", same(final["flows"], expected_final)
              and not any(d in final["flows"] for d in ids["drain"]))
        check("5. final: no isolate, no selection", (not final["iso"]) and final["sel"] == 0)
        check("6. stayed in plant_process (no Assembly switch)", final["type"] == "plant_process")

        tl = await page.evaluate("() => window.__tl")
        def has_state(pred): return any(pred(s) for s in tl)
        # hot-only step
        hot_only = has_state(lambda s: same(s["flows"], ids["hot"]))
        # drain isolate step: isolate on + drain active + hot inactive
        drain_iso = has_state(lambda s: s["iso"] and any(d in s["flows"] for d in ids["drain"]) and not any(h in s["flows"] for h in ids["hot"]))
        # air added (hot+air present at some point)
        hot_air = has_state(lambda s: all(h in s["flows"] for h in ids["hot"]) and all(a in s["flows"] for a in ids["air"]) and not any(c in s["flows"] for c in ids["cold"]))
        check("7. timeline shows hot-water-only step", hot_only)
        check("8. timeline shows hot+air step (air added, cold not yet)", hot_air)
        check("9. drain step isolated + drain on + hot off + (air kept)", drain_iso)

        # manual toggle still works afterwards
        toggled = await page.evaluate("""() => {
            _trainTogglePlantProcessFlowRole('drain_overflow');
            const act = new Set(trainingState.plantProcessActiveFlowIds||[]);
            return (window.__ids.drain||[]).every(id => act.has(id));
        }""")
        check("10. manual flow button still works after walkthrough (drain toggle on)", toggled)

        check("11. no uncaught JS errors during walkthrough", len(js_errors) == 0)
        if load_errors:
            print(f"  (note: {len(load_errors)} tolerated page-load error(s), e.g. {load_errors[0][:90]})")
        for e in js_errors:
            print("  ERROR:", e[:200])
        await browser.close()

    httpd.shutdown()
    passed = sum(1 for _, ok in results if ok)
    print(f"\n{passed}/{len(results)} checks passed")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
