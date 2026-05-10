"""Browser smoke check for the new global top-toolbar icons.

Validates:
  1. All 9 .global-toolbar-icon <img> elements exist (one per #icon* button)
     and resolve to unique PNG sources.
  2. Each image is fully loaded (complete && naturalWidth=24, naturalHeight=24).
  3. The 9 buttons retain their original ids (Home, Open, Save, Print, Undo,
     Redo, Select, News, Settings).
  4. Click each button (where a handler exists) — no JS errors.
  5. Toggle dark/light theme — no JS errors, icons still load.
  6. Training tab still uses its 10 .ribbon-training-icon images (untouched).

Captures:
  - global_toolbar_dark.png  (dark mode)
  - global_toolbar_light.png (light mode)
  - global_toolbar_buttons_close_dark.png
  - global_toolbar_buttons_close_light.png
"""
import asyncio, sys
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from playwright.async_api import async_playwright

APP_URL = "http://127.0.0.1:8012/static/index.html"
WORKTREE = Path(r"C:\Users\skaumb\OneDrive - continentalmachines.com\Desktop\Projects\AI-tool\.claude\worktrees\training-solidworks-layout-2026-05-10")
SHOTS = WORKTREE / "_train_browser_shots"
SHOTS.mkdir(exist_ok=True)

BUTTON_IDS = ['iconHome','iconOpen','iconSave','iconPrint','iconUndo','iconRedo','iconSelect','iconNews','iconSettings']
EXPECTED_FILES = ['home.png','file.png','save.png','printer.png','undo.png','redo.png','cursor.png','bell.png','gear.png']


async def capture_toolbar(page, label, suffix):
    box = await page.evaluate(
        """() => {
            const t = document.querySelector('.toolbar-icons');
            if (!t) return null;
            const b = t.getBoundingClientRect();
            return { x: Math.max(0, b.x - 2), y: Math.max(0, b.y - 2), w: b.width + 4, h: b.height + 4 };
        }"""
    )
    if not box: return
    await page.screenshot(
        path=str(SHOTS / f"global_toolbar_{suffix}.png"),
        clip={"x": box["x"], "y": box["y"], "width": box["w"], "height": box["h"]},
    )
    print(f"     screenshot: global_toolbar_{suffix}.png")


async def inspect_icons(page):
    """Read DOM state for the 9 toolbar icons."""
    return await page.evaluate(
        """({ buttonIds, expectedFiles }) => {
            const out = { perButton: [], allCount: 0, uniqueSrcCount: 0, allLoaded: true, allCorrectFile: true };
            const allImgs = document.querySelectorAll('.toolbar-icons .global-toolbar-icon');
            out.allCount = allImgs.length;
            out.uniqueSrcCount = (new Set(Array.from(allImgs).map(i => i.getAttribute('src')))).size;
            buttonIds.forEach((id, idx) => {
                const btn = document.getElementById(id);
                if (!btn) { out.perButton.push({ id, ok: false, reason: 'missing-button' }); out.allLoaded = false; return; }
                const img = btn.querySelector('img.global-toolbar-icon');
                if (!img) { out.perButton.push({ id, ok: false, reason: 'no-img' }); out.allLoaded = false; return; }
                const src = img.getAttribute('src') || '';
                const fileMatch = src.endsWith('/' + expectedFiles[idx]);
                const loaded = !!img.complete && img.naturalWidth > 0;
                if (!loaded) out.allLoaded = false;
                if (!fileMatch) out.allCorrectFile = false;
                out.perButton.push({
                    id,
                    src: src.split('/').pop(),
                    expected: expectedFiles[idx],
                    fileMatch,
                    loaded,
                    nat: [img.naturalWidth, img.naturalHeight],
                });
            });
            return out;
        }""",
        { "buttonIds": BUTTON_IDS, "expectedFiles": EXPECTED_FILES },
    )


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
        await page.wait_for_timeout(400)

        # ── Check 1+2+3: dark mode inspection ──
        # Force dark to be deterministic regardless of localStorage
        await page.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
        await page.wait_for_timeout(150)
        await page.wait_for_function(
            "() => document.querySelectorAll('.toolbar-icons .global-toolbar-icon').length === 9",
            timeout=4000,
        )
        await page.wait_for_function(
            """() => {
                const imgs = document.querySelectorAll('.toolbar-icons .global-toolbar-icon');
                return imgs.length === 9 && Array.from(imgs).every(i => i.complete && i.naturalWidth > 0);
            }""",
            timeout=5000,
        )
        dark = await inspect_icons(page)
        print("\n[DARK] toolbar inspection:")
        for r in dark['perButton']:
            print(f"   {r['id']:<14s} src={r.get('src','-'):<12s} expected={r.get('expected','-'):<12s} match={r.get('fileMatch')} loaded={r.get('loaded')} nat={r.get('nat')}")
        print(f"   count={dark['allCount']} uniqueSrc={dark['uniqueSrcCount']} allLoaded={dark['allLoaded']} allCorrectFile={dark['allCorrectFile']}")
        await capture_toolbar(page, "dark", "dark")

        check_dark = (
            dark['allCount'] == 9
            and dark['uniqueSrcCount'] == 9
            and dark['allLoaded']
            and dark['allCorrectFile']
            and all(r.get('nat') == [24, 24] for r in dark['perButton'])
        )

        # ── Check 4: click each button — no JS error ──
        click_errors_before = len(js_errors)
        for bid in BUTTON_IDS:
            try:
                await page.evaluate(f"() => document.getElementById('{bid}')?.click()")
                await page.wait_for_timeout(120)
                # Some buttons open modals; close any modal/popup that may have appeared
                await page.keyboard.press("Escape")
                await page.wait_for_timeout(80)
            except Exception as e:
                print(f"   click {bid} threw: {e}")
        click_errors_after = len(js_errors)
        new_click_errors = js_errors[click_errors_before:click_errors_after]
        check_clicks = len(new_click_errors) == 0
        print(f"\n[CLICK] all 9 buttons clicked, JS errors triggered: {len(new_click_errors)}")
        if new_click_errors:
            for e in new_click_errors[:3]:
                print(f"    - {e[:200]}")

        # ── Check 5: toggle to light mode ──
        await page.evaluate("() => document.documentElement.setAttribute('data-theme', 'light')")
        await page.wait_for_timeout(300)
        await page.wait_for_function(
            """() => {
                const imgs = document.querySelectorAll('.toolbar-icons .global-toolbar-icon');
                return imgs.length === 9 && Array.from(imgs).every(i => i.complete && i.naturalWidth > 0);
            }""",
            timeout=5000,
        )
        light = await inspect_icons(page)
        print("\n[LIGHT] toolbar inspection:")
        print(f"   count={light['allCount']} uniqueSrc={light['uniqueSrcCount']} allLoaded={light['allLoaded']} allCorrectFile={light['allCorrectFile']}")
        await capture_toolbar(page, "light", "light")
        check_light = (
            light['allCount'] == 9
            and light['uniqueSrcCount'] == 9
            and light['allLoaded']
            and light['allCorrectFile']
        )

        # ── Check 6: Training tab — ribbon icons untouched ──
        await page.evaluate("() => switchTab('training')")
        await page.wait_for_function(
            "() => document.querySelectorAll('#contextRibbon .ribbon-training-icon').length === 10",
            timeout=4000,
        )
        await page.wait_for_function(
            """() => {
                const imgs = document.querySelectorAll('#contextRibbon .ribbon-training-icon');
                return imgs.length === 10 && Array.from(imgs).every(i => i.complete && i.naturalWidth > 0);
            }""",
            timeout=5000,
        )
        training_inspect = await page.evaluate(
            """() => {
                const imgs = document.querySelectorAll('#contextRibbon .ribbon-training-icon');
                return {
                    count: imgs.length,
                    natural_all_128: Array.from(imgs).every(i => i.naturalWidth === 128 && i.naturalHeight === 128),
                    unique_srcs: (new Set(Array.from(imgs).map(i => i.src))).size,
                };
            }"""
        )
        check_training_intact = (
            training_inspect.get("count") == 10
            and training_inspect.get("natural_all_128") is True
            and training_inspect.get("unique_srcs") == 10
        )
        print(f"\n[TRAINING] ribbon untouched: {check_training_intact}  ({training_inspect})")
        await page.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
        await page.wait_for_timeout(150)

        # ── Final: tab back to default, capture wider toolbar shot ──
        await page.evaluate("() => switchTab('drawing')")
        await page.wait_for_timeout(200)
        await page.evaluate("() => document.documentElement.setAttribute('data-theme', 'dark')")
        await page.wait_for_timeout(120)
        await capture_toolbar(page, "dark wide", "buttons_close_dark")
        await page.evaluate("() => document.documentElement.setAttribute('data-theme', 'light')")
        await page.wait_for_timeout(150)
        await capture_toolbar(page, "light wide", "buttons_close_light")

        await browser.close()

        # Results
        print()
        print("=" * 60)
        print("RESULTS")
        print("=" * 60)
        results = [
            ("1. Dark: 9 unique icons, all loaded, correct files", check_dark),
            ("2. Light: 9 unique icons, all loaded, correct files", check_light),
            ("3. Click all 9 buttons → no JS error",                check_clicks),
            ("4. Training ribbon (10 PNG icons) still intact",      check_training_intact),
        ]
        for label, ok in results:
            print(f"  {label:<54s} {'PASS' if ok else 'FAIL'}")
        all_ok = all(ok for _, ok in results)
        if js_errors:
            print(f"\n  Note: total JS errors during run: {len(js_errors)}")
            for e in js_errors[:3]:
                print(f"    - {e[:200]}")
        print(f"\n  RESULT: {'PASS' if all_ok else 'FAIL'}")
        sys.exit(0 if all_ok else 1)


asyncio.run(main())
