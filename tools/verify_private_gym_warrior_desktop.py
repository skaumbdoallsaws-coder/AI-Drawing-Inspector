"""Verify the saved warrior walls in the normal desktop without editing the layout."""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path.home() / 'AppData/Roaming/Python/Python314/site-packages'))
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'
from PIL import Image
from playwright.sync_api import sync_playwright

CURRENT = 'window._trainFacilityLayoutAuthoringApp'
IDS = ['viking', 'zulu', 'samurai', 'mongol-archer', 'spartan']


def verify():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cdp', default='http://127.0.0.1:9542')
    parser.add_argument('--origin', default='http://127.0.0.1:8480')
    args = parser.parse_args()
    out = ROOT / '.runtime/private-gym-warrior-trim-20261010/desktop'
    out.mkdir(parents=True, exist_ok=True)
    path = ROOT / '.runtime/facility-layout/layouts/local/site-local/layouts/fl-private-gym-20261007.json'
    before = path.read_bytes()
    saved = json.loads(before)
    report = dict(status='running', scope='Full normal desktop scene', captures=[], assets=[])
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(args.cdp, timeout=20000)
            page = next(v for c in browser.contexts for v in c.pages
                        if v.url.startswith(args.origin.rstrip('/') + '/'))
            page.wait_for_function(CURRENT + '?.session?.getState().loaded', timeout=120000)
            state = page.evaluate(CURRENT + '.session.getState()')
            assert state['layout'] == saved, 'Desktop differs from saved layout'
            assert not state['dirty'], 'Leave unsaved edits untouched'
            page.evaluate(CURRENT + ".workspace._setViewMode('3d')")
            page.evaluate(CURRENT + ".workspace.threeAdapter.exitWalkthrough('wall-review')")
            page.wait_for_function(CURRENT + '.workspace.threeAdapter.getDiagnostics().pendingLoads===0', timeout=120000)
            page.wait_for_function('ids=>ids.every(id=>' + CURRENT + '.workspace.threeAdapter.getDiagnostics().exteriorArtwork.some(a=>a.artworkId===id&&a.status==="ready"))',
                                   arg=['hall-warrior-' + key for key in IDS], timeout=60000)
            diagnostic = page.evaluate(CURRENT + '.workspace.threeAdapter.getDiagnostics()')
            catalog = page.evaluate(CURRENT + '.workspace.assetCatalog.map(a=>a.source)')
            arts = {a['artworkId']: a for a in diagnostic['exteriorArtwork']}

            def camera(position, target):
                page.evaluate('([position,target])=>{const a=' + CURRENT + '.workspace.threeAdapter;const v=a.getCameraView();Object.assign(v,{position,target,up:{x:0,y:1,z:0},fov:65,near:.05,far:250});a.applyCameraView(v)}',
                              [position, target])
                page.wait_for_timeout(500)

            def capture(name):
                raw = page.screenshot(path=str(out / (name + '.png')), timeout=20000)
                canvas = page.locator('#trainFacilityLayoutAuthoring canvas:visible').last
                pixels = Image.open(io.BytesIO(canvas.screenshot(timeout=20000))).convert('RGB')
                assert len(set(pixels.getdata())) > 1000, 'Blank or incomplete canvas'
                report['captures'].append(dict(name=name, screenshotHash=hashlib.sha256(raw).hexdigest()))

            for key in IDS:
                art = arts['hall-warrior-' + key]
                placement = next(p for p in saved['placements'] if p['placementId'] == art['target']['placementId'])
                assert placement['assetId'].endswith('-gold-edge')
                group = next(g for g in diagnostic['representationGroups'] if g['assetId'] == placement['assetId'])
                assert group['assetDefinitionRevision'] == placement['assetDefinitionRevision']
                assert group['representation'] in ('overview', 'detail')
                assert group['prototypeMeshCount'] == 3, 'Wall and gold face primitives must be loaded'
                asset = next(a for a in catalog if a['assetId'] == placement['assetId'])
                url = asset['overview']['path']
                # Electron supplies its local asset authorization to renderer fetches.
                response = page.evaluate('async url=>{const r=await fetch(url);const bytes=await r.arrayBuffer();const hash=await crypto.subtle.digest("SHA-256",bytes);return {ok:r.ok,status:r.status,sha256:Array.from(new Uint8Array(hash),v=>v.toString(16).padStart(2,"0")).join("")}}', url)
                assert response['ok'], (url, response['status'])
                digest = response['sha256']
                assert digest == hashlib.sha256((ROOT / url.lstrip('/')).read_bytes()).hexdigest()
                report['assets'].append(dict(placementId=placement['placementId'], artifact=url, sha256=digest))
                target = art['worldPosition']
                position = dict(target)
                position['y'] = 1.65
                if key == 'spartan':
                    position['x'] = target['x'] + 3.3
                else:
                    position['z'] = -0.2
                camera(position, target)
                capture(key)
            camera(dict(x=21, y=1.7, z=-.45), dict(x=16, y=1.5, z=-2.95))
            capture('hallway')
            after = page.evaluate(CURRENT + '.session.getState()')
            assert after['layout'] == saved and not after['dirty']
            assert after['selection'] == state['selection']
            assert path.read_bytes() == before
            final = page.evaluate(CURRENT + '.workspace.threeAdapter.getDiagnostics()')
            assert final['walkthroughContextFocus'] is None
            assert not final['warnings'], final['warnings']
            report.update(status='passed', updatedAt=saved['updatedAt'], savedBytesUnchanged=True,
                          selectionUnchanged=True, warnings=final['warnings'], artwork=arts,
                          visualReview='Screenshots require separate visual inspection')
            # Disconnect only; closing this browser would close the user's desktop app.
    except Exception as error:
        report.update(status='failed', error=str(error))
        raise
    finally:
        (out / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(dict(status=report['status'], walls=len(report['assets']), captures=len(report['captures']))))


if __name__ == '__main__':
    verify()
