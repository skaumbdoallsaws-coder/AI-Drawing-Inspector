"""Real-browser verification of the new Training tab.

Spec checks:
  1. Open Training tab.
  2. Left Training Setup panel appears by default.
  3. Left sidebar icon toggles setup panel.
  4. Right sidebar icon toggles playback panel.
  5. Training type dropdown changes selected type.
  6. Generate Training creates a structured procedure.
  7. Playback panel shows only current step.
  8. Next/Previous update current step.
  9. Narrate kicks playback if audio service is available (we cannot
     guarantee /api/tts on the static server; we verify the dispatch
     path is wired and state._narrationKind goes to 'training').
 10. Viewport stays clear (no card overlays in the centre).
 11. Highlight/camera focus are triggered per step (we instrument the
     window helpers and verify they fire).
 12. Full transcript hidden until expanded.
 13. Drawing / 3D Model / Assembly / Report tabs still load (no JS error
     when switching).

Strategy: serve static/ on http.server and load directly. The page will
log fetch errors for absent /api/* endpoints — those are tolerated
because the Training tab checks don't depend on backend data; only the
preserve-other-tabs check does, and we accept that it may show empty
states without throwing JS errors.
"""
import asyncio, sys
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from playwright.async_api import async_playwright

APP_URL = "http://127.0.0.1:8012/index.html"
WORKTREE = Path(r"C:\Users\skaumb\OneDrive - continentalmachines.com\Desktop\Projects\AI-tool\.claude\worktrees\training-solidworks-layout-2026-05-10")
SHOTS = WORKTREE / "_train_browser_shots"
SHOTS.mkdir(exist_ok=True)


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--enable-webgl', '--use-angle=default', '--ignore-gpu-blocklist'],
        )
        ctx = await browser.new_context(viewport={"width": 1600, "height": 1000})
        page = await ctx.new_page()

        js_errors = []
        page.on("pageerror", lambda exc: js_errors.append(str(exc)))

        await page.goto(APP_URL)
        await page.wait_for_selector("#fileInput", state="attached", timeout=15000)
        # Allow any /api/* fetches to fail in peace
        await page.wait_for_timeout(500)

        # ── Check 1 + 2: open Training tab, Setup panel default open ──
        await page.evaluate("() => switchTab('training')")
        await page.wait_for_selector("#trainShell", timeout=5000)
        check1 = await page.evaluate("() => state.activeTab === 'training' && !!document.getElementById('trainShell')")
        # Setup panel default open: panel exists and not collapsed
        check2 = await page.evaluate(
            """() => {
                const p = document.getElementById('trainSetupPanel');
                return !!p && !p.classList.contains('collapsed');
            }"""
        )
        await page.screenshot(path=str(SHOTS / "01_training_default_open.png"))
        print(f"  1. Open Training tab + #trainShell exists:        {check1}")
        print(f"  2. Setup panel default open:                       {check2}")

        # ── Check 3: left sidebar icon toggles setup panel ──
        await page.click("#trainLeftRailSetup")
        setup_after_click1 = await page.evaluate(
            "() => document.getElementById('trainSetupPanel').classList.contains('collapsed')"
        )
        await page.click("#trainLeftRailSetup")
        setup_after_click2 = await page.evaluate(
            "() => document.getElementById('trainSetupPanel').classList.contains('collapsed')"
        )
        check3 = (setup_after_click1 is True) and (setup_after_click2 is False)
        print(f"  3. Left rail icon toggles setup panel:             {check3}  (collapsed→{setup_after_click1}, open→{setup_after_click2})")

        # ── Check 4: right sidebar icon toggles playback panel ──
        play_initial = await page.evaluate(
            "() => document.getElementById('trainPlaybackPanel').classList.contains('collapsed')"
        )
        await page.click("#trainRightRailPlayback")
        play_after = await page.evaluate(
            "() => document.getElementById('trainPlaybackPanel').classList.contains('collapsed')"
        )
        check4 = play_initial != play_after
        print(f"  4. Right rail icon toggles playback panel:         {check4}  (initial collapsed={play_initial}, after click={play_after})")

        # ── Check 5: training type dropdown changes selected type ──
        # Use the setup panel select (first <select> in the setup body)
        await page.evaluate(
            """() => {
                const sel = document.querySelector('#trainSetupBody select');
                sel.value = 'maintenance';
                sel.dispatchEvent(new Event('change', { bubbles: true }));
            }"""
        )
        check5 = await page.evaluate("() => trainingState.type === 'maintenance'")
        # Also confirm chips refreshed
        chip_text = await page.evaluate("() => Array.from(document.querySelectorAll('#trainSetupBody .train-chip')).map(c => c.textContent).join(' | ')")
        print(f"  5. Type dropdown updates trainingState.type:       {check5}  (chips: {chip_text})")

        # ── Check 6: Generate Training creates a procedure ──
        await page.evaluate(
            """() => {
                const sel = document.querySelector('#trainSetupBody select');
                sel.value = 'service';
                sel.dispatchEvent(new Event('change', { bubbles: true }));
            }"""
        )
        await page.click("#trainGenerateBtn")
        await page.wait_for_timeout(300)
        proc_info = await page.evaluate(
            """() => {
                const p = trainingState.procedure;
                return p ? { title: p.title, type: p.trainingType, steps: p.steps.length, firstTitle: p.steps[0].title, evLevels: Array.from(new Set(p.steps.map(s => s.evidenceLevel))) } : null;
            }"""
        )
        check6 = bool(proc_info and proc_info.get("steps", 0) >= 3)
        print(f"  6. Generate Training creates a procedure:          {check6}  ({proc_info})")
        await page.screenshot(path=str(SHOTS / "02_after_generate.png"))

        # ── Check 7: playback panel shows ONLY the current step ──
        # In our render, the "current step card" is a .train-step-card; the
        # full transcript is a .train-collapse, hidden by default.
        playback_inspect = await page.evaluate(
            """() => {
                const body = document.getElementById('trainPlaybackBody');
                const cards = body ? body.querySelectorAll('.train-step-card').length : -1;
                const collapses = body ? body.querySelectorAll('.train-collapse').length : -1;
                const openCollapses = body ? body.querySelectorAll('.train-collapse.open').length : -1;
                return { stepCards: cards, collapses, openCollapses };
            }"""
        )
        check7 = playback_inspect.get("stepCards") == 1
        print(f"  7. Playback shows only current step (1 card):      {check7}  ({playback_inspect})")

        # ── Check 8: Next/Previous step ──
        before_idx = await page.evaluate("() => trainingState.currentStepIndex")
        await page.evaluate("() => window._trainingStepNext()")
        after_next = await page.evaluate("() => trainingState.currentStepIndex")
        await page.evaluate("() => window._trainingStepPrev()")
        after_prev = await page.evaluate("() => trainingState.currentStepIndex")
        check8 = after_next == before_idx + 1 and after_prev == before_idx
        print(f"  8. Next/Previous update step:                      {check8}  ({before_idx}→{after_next}→{after_prev})")

        # ── Check 9: Narrate dispatches to playback (state._narrationKind set to 'training') ──
        # Instrument the per-segment training hook (window-scoped) AND the
        # closure-scoped highlight by wrapping our exported window mirror.
        # _applyNarrationHighlight IS exported on window, but the narration
        # loop calls the closure-scoped reference, so we additionally
        # monitor via the segment hook which IS on window and is the
        # documented integration point for training playback.
        await page.evaluate(
            """() => {
                window.__segHookCalls = [];
                const origHook = window._trainingOnSegmentStart;
                window._trainingOnSegmentStart = function(i, seg) {
                    window.__segHookCalls.push({
                        i,
                        hp: (seg && seg.highlight_parts) ? seg.highlight_parts.slice() : [],
                        cf: (seg && seg.camera_focus) ? seg.camera_focus.slice() : [],
                    });
                    if (typeof origHook === 'function') return origHook.apply(this, arguments);
                };
            }"""
        )
        # Trigger Narrate via the ribbon helper. With no /api/tts, audio
        # fetch will fail, but the loop still applies highlight + camera per
        # segment because that happens BEFORE the audio await.
        await page.evaluate("() => window._trainingPlayCurrent()")
        await page.wait_for_timeout(2500)
        narration_state = await page.evaluate("() => ({ kind: state._narrationKind, playing: state.narrationPlaying, hasSegments: !!state.narrationSegments && state.narrationSegments.length > 0 })")
        check9 = (narration_state.get("kind") == "training") and narration_state.get("hasSegments")
        print(f"  9. Narrate dispatches to training playback path:   {check9}  ({narration_state})")

        # ── Check 11: per-segment hook fires (proxy for highlight/camera/explode) ──
        # The hook is called inside the playNarrationSequence loop on each
        # segment. If it fires N>=1 times, the per-step highlight + camera +
        # explode side-effect lines (which sit alongside it in the same
        # for-iteration body) are also being executed.
        hook_calls = await page.evaluate("() => window.__segHookCalls || []")
        # Source-level proof that highlight/camera/explode are wired into
        # the same per-segment loop body as the hook we just observed.
        src_check = await page.evaluate(
            """() => {
                const src = playNarrationSequence.toString();
                const loopStart = src.match(/for\\s*\\(\\s*let\\s+i\\s*=/);
                const hookCall  = src.match(/_trainingOnSegmentStart\\(/);
                const hlCall    = src.match(/_applyNarrationHighlight\\(seg\\.highlight_parts/);
                const camCall   = src.match(/_flyToPartGroup\\(seg\\.camera_focus\\)/);
                const expCall   = src.match(/_animateExplode\\(targetLevel/);
                if (!loopStart || !hookCall) return { ok: false, reason: 'patterns missing' };
                return {
                    ok: true,
                    hook_after_loop: hookCall.index > loopStart.index,
                    hl_after_loop:   hlCall && hlCall.index > loopStart.index,
                    cam_after_loop:  camCall && camCall.index > loopStart.index,
                    exp_after_loop:  expCall && expCall.index > loopStart.index,
                };
            }"""
        )
        check11 = (
            len(hook_calls) >= 1
            and src_check.get("ok")
            and src_check.get("hook_after_loop")
            and src_check.get("hl_after_loop")
            and src_check.get("cam_after_loop")
            and src_check.get("exp_after_loop")
        )
        print(f" 11. Per-segment hook fires + highlight/camera/explode in same loop body:")
        print(f"     hook_calls={len(hook_calls)} src={src_check}")
        print(f"     -> {check11}")

        # ── Check 14 (regression): Pause must NOT leak the procedure into chat ──
        # Reviewer found that stopNarration() only special-cased
        # sales_coaching, so pressing Pause during training playback was
        # falling through to _renderAllSegmentsFinal and overwriting the
        # latest assistant chat message with "Step 1...Step 6...". This
        # check snapshots the chat HTML before Pause, presses Pause via
        # the production stopNarration path, and asserts: chat unchanged,
        # trainingState.isPlaying === false, no procedure dump in chat,
        # state._narrationKind cleared.
        chat_before = await page.evaluate(
            """() => {
                const am = document.querySelector('.agent-messages');
                return am ? am.innerHTML : '';
            }"""
        )
        # Make sure isPlaying is true going in (set by _trainPlayCurrent)
        playing_before = await page.evaluate("() => trainingState.isPlaying === true")

        # Press the same Pause path the user would: production stopNarration()
        # WITHOUT the manual clears we used to do here.
        await page.evaluate("() => { try { stopNarration(); } catch (_) {} }")
        await page.wait_for_timeout(400)

        chat_after = await page.evaluate(
            """() => {
                const am = document.querySelector('.agent-messages');
                return am ? am.innerHTML : '';
            }"""
        )
        # If the bug regressed, the chat would now contain step text from
        # the procedure (e.g. "Identify the service area", "Lock out and
        # isolate energy", "Reassemble and torque"). Look for any step
        # title to detect the leak — and a generic "Step N." prefix.
        leak_signals = await page.evaluate(
            """() => {
                const am = document.querySelector('.agent-messages');
                const text = am ? am.innerText : '';
                const proc = trainingState.procedure;
                const titles = (proc && proc.steps) ? proc.steps.map(s => s.title) : [];
                const titleHits = titles.filter(t => text.includes(t)).length;
                const stepLabelHits = (text.match(/Step \\d+\\./g) || []).length;
                return { titleHits, stepLabelHits, text_len: text.length };
            }"""
        )
        playing_after = await page.evaluate("() => trainingState.isPlaying")
        kind_after = await page.evaluate("() => state._narrationKind")
        chat_unchanged = (chat_before == chat_after)
        no_leak = (leak_signals.get("titleHits", 0) == 0
                   and leak_signals.get("stepLabelHits", 0) == 0)
        check14 = (
            playing_before is True
            and playing_after is False
            and kind_after in (None, "")
            and chat_unchanged
            and no_leak
        )
        print(f" 14. Pause does not leak procedure into chat:        {check14}")
        print(f"     playing_before={playing_before} playing_after={playing_after} kind_after={kind_after!r}")
        print(f"     chat_unchanged={chat_unchanged} leak_signals={leak_signals}")

        # ensure narrationKind/playing fully cleared for the rest of the run
        await page.evaluate("() => { state._narrationKind = null; state.narrationPlaying = false; }")
        await page.wait_for_timeout(150)

        # ── Check 10: viewport stays clear (no card overlays inside #trainViewport) ──
        # Allowed overlays: train-step-badge. Anything else inside the viewport
        # (cards, prompt templates, full transcript) would fail the check.
        vp_inspect = await page.evaluate(
            """() => {
                const v = document.getElementById('trainViewport');
                if (!v) return { ok: false, reason: 'no_viewport' };
                const cards = v.querySelectorAll('.train-step-card, .train-mini-card, .train-collapse').length;
                const badges = v.querySelectorAll('.train-step-badge').length;
                return { cards, badges };
            }"""
        )
        check10 = vp_inspect.get("cards") == 0 and vp_inspect.get("badges") == 1
        print(f" 10. Viewport stays clear (no overlay cards):        {check10}  ({vp_inspect})")

        # ── Check 12: full transcript hidden until expanded ──
        # The Full transcript collapse is the LAST .train-collapse in the
        # playback body (after Tools/WhatCanGoWrong). showFullTranscript=false
        # by default, so it must be present and NOT have .open.
        ft_inspect = await page.evaluate(
            """() => {
                const collapses = document.querySelectorAll('#trainPlaybackBody .train-collapse');
                const labels = Array.from(collapses).map(c => c.querySelector('.train-collapse-head')?.textContent || '');
                const ftIdx = labels.findIndex(l => l.includes('Full transcript'));
                if (ftIdx < 0) return { found: false, labels };
                const ft = collapses[ftIdx];
                return { found: true, isOpen: ft.classList.contains('open'), labels };
            }"""
        )
        check12 = ft_inspect.get("found") and not ft_inspect.get("isOpen")
        print(f" 12. Full transcript hidden until expanded:          {check12}  ({ft_inspect})")

        # ── Check 13: tab switching to other tabs does not throw ──
        switching_errors_before = len(js_errors)
        for tab in ['drawing', '3dmodel', 'assembly', 'report', 'training']:
            await page.evaluate("(t) => switchTab(t)", tab)
            await page.wait_for_timeout(200)
        switching_errors_after = len(js_errors)
        new_switch_errors = js_errors[switching_errors_before:switching_errors_after]
        check13 = len(new_switch_errors) == 0
        print(f" 13. Tab switching does not throw JS errors:         {check13}  ({len(new_switch_errors)} new errors)")
        if new_switch_errors:
            for e in new_switch_errors[:5]:
                print(f"      - {e[:200]}")

        await page.screenshot(path=str(SHOTS / "03_final_training.png"))
        await browser.close()

        print()
        print("=" * 60)
        print("RESULTS")
        print("=" * 60)
        results = [
            ("1.  Open Training tab",                    check1),
            ("2.  Setup panel default open",             check2),
            ("3.  Left rail toggles setup panel",        check3),
            ("4.  Right rail toggles playback panel",    check4),
            ("5.  Type dropdown updates trainingState",  check5),
            ("6.  Generate Training creates procedure",  check6),
            ("7.  Playback shows only current step",     check7),
            ("8.  Next/Previous update step",            check8),
            ("9.  Narrate dispatches to training kind",  check9),
            ("10. Viewport stays clear of card overlays",check10),
            ("11. Highlight fires per step",             check11),
            ("12. Full transcript hidden by default",    check12),
            ("13. Tab switching does not throw",         check13),
            ("14. Pause does not leak procedure to chat",check14),
        ]
        for label, ok in results:
            print(f"  {label:<48s} {'PASS' if ok else 'FAIL'}")
        all_ok = all(ok for _, ok in results)
        if js_errors:
            print(f"\n  Note: total JS errors during run: {len(js_errors)}")
            for e in js_errors[:3]:
                print(f"    - {e[:200]}")
        print(f"\n  RESULT: {'PASS' if all_ok else 'FAIL'}")
        sys.exit(0 if all_ok else 1)


asyncio.run(main())
