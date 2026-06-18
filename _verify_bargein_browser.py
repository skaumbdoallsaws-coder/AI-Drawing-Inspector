"""Real-browser behavior test for Phase-1 spacebar push-to-talk barge-in.

Drives the actual served app (not symbol-existence guards). Uses Chromium's
fake-media-stream flags so getUserMedia / MediaRecorder / AudioContext work
headlessly without a real microphone or a permission prompt.

Checks (behavior, not names):
  1. Space keydown during narration pauses Sage (narrationState -> paused_listening),
     opening the mic (the existing _pauseNarrationForBargeIn path).
  2. The pause revokes the prefetched next-segment URL and nulls the promise (no
     per-interruption object-URL / synthesize leak).  [invariant T2]
  3. narrationSessionId is NOT bumped on barge-in onset (else the interruption's own
     transcription would be discarded by the stale guard).  [invariant T1]
  4. _pttHeld is true while held and false after keyup; recording is released.
  5. Quick tap (keyup before recording exists) leaves no stuck hold (_pttHeld false).
  6. Missed-keyup safety: window blur during a hold force-releases (_pttHeld false).
  7. Space typed inside an INPUT/TEXTAREA does NOT trigger barge-in (typing guard).
  8. No uncaught JS error is produced by any of the interactions above.

Serves static/ on a local loopback http.server (127.0.0.1 is a secure context, so
getUserMedia is allowed). Tolerates /api/* 404s like the other _verify_* scripts.
"""
import asyncio
import sys
import threading
import functools
import http.server
import socketserver
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent  # serves so /static/index.html resolves


def _serve(directory):
    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(directory))
    httpd = socketserver.ThreadingTCPServer(("127.0.0.1", 0), handler)
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, port


SETUP_NARRATING = """() => {
    state.narrationState = 'narrating';
    state.narrationPlaying = true;
    state.narrationSegments = [
        { text: 'segment zero', highlight_parts: [] },
        { text: 'segment one', highlight_parts: [] },
    ];
    state.narrationSegmentIndex = 0;
    state._narrationKind = 'walkthrough';
    state._pttHeld = false;
    state._pttStopRequested = false;
}"""

KEY = """(t) => {
    const ev = (type) => document.dispatchEvent(
        new KeyboardEvent(type, { code: 'Space', key: ' ', bubbles: true, cancelable: true }));
    ev(t);
}"""


async def main():
    httpd, port = _serve(ROOT)
    url = f"http://127.0.0.1:{port}/static/index.html"
    results = []

    def check(name, ok):
        results.append((name, bool(ok)))
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--use-fake-device-for-media-stream",
                "--use-fake-ui-for-media-stream",
                "--enable-webgl",
                "--use-angle=swiftshader",
                "--ignore-gpu-blocklist",
                "--autoplay-policy=no-user-gesture-required",
            ],
        )
        ctx = await browser.new_context(
            viewport={"width": 1400, "height": 900},
            permissions=["microphone"],
        )
        page = await ctx.new_page()
        js_errors = []
        page.on("pageerror", lambda exc: js_errors.append(str(exc)))

        await page.goto(url)
        await page.wait_for_selector("#fileInput", state="attached", timeout=20000)
        await page.wait_for_timeout(600)  # let /api/* fetches fail in peace

        # Install a revoke tracker once.
        await page.evaluate(
            """() => {
                window.__revoked = [];
                const orig = URL.revokeObjectURL.bind(URL);
                URL.revokeObjectURL = (u) => { window.__revoked.push(u); try { orig(u); } catch (e) {} };
            }"""
        )

        load_errors = list(js_errors)
        js_errors.clear()

        # ── Check 1 + 2 + 3: keydown pauses, revokes prefetch, no session bump ──
        await page.evaluate(SETUP_NARRATING)
        await page.evaluate(
            "() => { state.narrationSessionId = 41; state.narrationPrefetchPromise = Promise.resolve('blob:fake-prefetch-1'); }"
        )
        session_before = await page.evaluate("() => state.narrationSessionId")
        await page.evaluate(KEY, "keydown")
        try:
            await page.wait_for_function("() => state.narrationState === 'paused_listening'", timeout=6000)
            paused = True
        except Exception:
            paused = False
        check("1. Space keydown during narration -> paused_listening (mic opens)", paused)

        await page.wait_for_timeout(150)  # let the revoke microtask run
        revoked = await page.evaluate(
            "() => window.__revoked.includes('blob:fake-prefetch-1') && state.narrationPrefetchPromise === null"
        )
        check("2. pause revokes prefetch URL + nulls promise (T2 leak fix)", revoked)

        session_after = await page.evaluate("() => state.narrationSessionId")
        check("3. narrationSessionId NOT bumped on onset (T1)", session_before == session_after == 41)

        held = await page.evaluate("() => state._pttHeld === true")
        check("4a. _pttHeld true while held", held)

        # ── Check 4b: keyup releases hold ──
        await page.evaluate(KEY, "keyup")
        try:
            await page.wait_for_function("() => state._pttHeld === false", timeout=4000)
            released = True
        except Exception:
            released = False
        check("4b. keyup clears _pttHeld (recording released)", released)

        # ── Check 5: quick tap (keydown immediately followed by keyup) ──
        await page.evaluate(SETUP_NARRATING)
        await page.evaluate(
            "() => { document.dispatchEvent(new KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true,cancelable:true})); document.dispatchEvent(new KeyboardEvent('keyup',{code:'Space',key:' ',bubbles:true,cancelable:true})); }"
        )
        await page.wait_for_timeout(700)
        quick_ok = await page.evaluate("() => state._pttHeld === false && state._pttStopRequested === true")
        check("5. quick tap leaves no stuck hold", quick_ok)

        # ── Check 6: missed-keyup safety via window blur ──
        await page.evaluate(SETUP_NARRATING)
        await page.evaluate(KEY, "keydown")
        await page.wait_for_function("() => state.narrationState === 'paused_listening'", timeout=6000)
        await page.evaluate("() => window.dispatchEvent(new Event('blur'))")
        try:
            await page.wait_for_function("() => state._pttHeld === false", timeout=4000)
            blur_ok = True
        except Exception:
            blur_ok = False
        check("6. window blur during hold force-releases _pttHeld", blur_ok)

        # ── Check 7: Space typed in an input does NOT trigger barge-in ──
        await page.evaluate(SETUP_NARRATING)
        typed_ok = await page.evaluate(
            """() => {
                const ta = document.createElement('textarea');
                document.body.appendChild(ta); ta.focus();
                ta.dispatchEvent(new KeyboardEvent('keydown',{code:'Space',key:' ',bubbles:true,cancelable:true}));
                ta.remove();
                return state.narrationState === 'narrating' && state._pttHeld === false;
            }"""
        )
        check("7. Space inside an input is ignored (typing guard)", typed_ok)

        # ── Check 8: Phase 2A — barge-in QUESTION shows working status immediately
        #            and does NOT navigate away from Training. Drives the real flow with
        #            only /api/voice/transcribe mocked (the question text); the answer
        #            endpoint is left to fail in the background after we assert. ──
        await page.evaluate(SETUP_NARRATING)
        await page.evaluate("() => { state._narrationKind = 'training'; state.activeTab = 'training'; }")
        await page.evaluate(
            """() => {
                window.__realFetch = window.fetch.bind(window);
                window.fetch = (url, opts) => {
                    const u = String(url);
                    if (u.includes('/api/voice/transcribe')) {
                        return Promise.resolve(new Response(
                            JSON.stringify({ text: 'why do we install this first' }),
                            { status: 200, headers: { 'Content-Type': 'application/json' } }));
                    }
                    return window.__realFetch(url, opts);
                };
            }"""
        )
        await page.evaluate(KEY, "keydown")
        await page.wait_for_function("() => state.narrationState === 'paused_listening'", timeout=6000)
        await page.evaluate(KEY, "keyup")
        try:
            await page.wait_for_function("() => state.narrationState === 'answering'", timeout=8000)
            reached = True
        except Exception:
            reached = False
        status_shown = await page.evaluate(
            "() => document.body.textContent.toLowerCase().includes('checking this step')"
        )
        no_nav = await page.evaluate("() => state.activeTab === 'training'")
        await page.evaluate("() => { if (window.__realFetch) { window.fetch = window.__realFetch; window.__realFetch = null; } }")
        check("8. barge-in question -> answering + working status shown + stays on Training",
              reached and status_shown and no_nav)

        # ── Check 9: no uncaught JS errors across all interactions ──
        check("9. no uncaught JS error from PTT / barge-in interactions", len(js_errors) == 0)

        if load_errors:
            print(f"  (note: {len(load_errors)} page-load error(s) tolerated, e.g. {load_errors[0][:120]})")
        if js_errors:
            for e in js_errors:
                print(f"  ERROR during interaction: {e[:200]}")

        await browser.close()

    httpd.shutdown()
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    print(f"\n{passed}/{total} checks passed")
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
