"""Playwright visual check on an isolated real manual layout. No provider or Save."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request

from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
PORT = 8498
BASE = f'http://127.0.0.1:{PORT}'
OUT = ROOT / '.runtime' / ('avatar-browser-' + time.strftime('%Y%m%d-%H%M%S'))
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
APP = '_trainFacilityLayoutAuthoringApp'
ADAPTER = APP + '.workspace.threeAdapter'


def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', PORT))
    subprocess.run([sys.executable, 'desktop/tools/prepare-application-check.py',
                    '--destination', str(OUT), '--port', str(PORT)], cwd=ROOT, check=True, creationflags=HIDDEN)
    source = json.loads((OUT / 'application-check-source.json').read_text())
    env = dict(os.environ, INSPECTORPRO_FACILITY_LAYOUT_ROOT=str(OUT / 'facility'),
               INSPECTORPRO_INDUSTRIAL_ASSET_LIBRARY='1')
    for name in ['VIEWER_V2', 'MANUAL_EDIT', 'CONSTRAINTS', 'ROUTING']:
        env['INSPECTORPRO_FACILITY_LAYOUT_' + name] = '1'
    report = {'status': 'running', 'output': str(OUT), 'errors': [], 'mutations': [], 'captures': []}
    def stage(name):
        report['stage'] = name
        (OUT / 'result.json').write_text(json.dumps(report, indent=2))
        print(name, flush=True)
    with (OUT / 'server.log').open('w', encoding='utf8') as log:
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1',
                                   '--port', str(PORT)], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=HIDDEN)
        try:
            stage('backend-start')
            deadline = time.monotonic() + 120
            while True:
                try:
                    with urllib.request.urlopen(BASE + '/api/facility-layout-bootstrap', timeout=3) as response:
                        if response.status == 200: break
                except Exception:
                    if server.poll() is not None or time.monotonic() > deadline: raise RuntimeError('Backend startup failed')
                    time.sleep(.5)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.set_default_navigation_timeout(120000)
                page.on('pageerror', lambda e: report['errors'].append(str(e)))
                page.on('request', lambda r: report['mutations'].append({'url': r.url, 'method': r.method})
                        if '/api/facility-layouts/' in r.url and r.method in ('POST', 'PUT', 'DELETE') else None)
                try:
                    stage('manual-load')
                    page.goto(BASE + '/?facilityLayoutId=fl-reference-manual-20260812', wait_until='domcontentloaded')
                    page.get_by_role('tab', name='Workflows', exact=True).click()
                    page.wait_for_selector('#trainingTypeRibbonSelect', state='attached')
                    page.evaluate("() => {const s=document.getElementById('trainingTypeRibbonSelect');s.value='facility_layout';s.dispatchEvent(new Event('change',{bubbles:true}));}")
                    page.wait_for_function('window.' + APP + '?.session.getState().loaded', timeout=120000)
                    original = page.evaluate(APP + '.session.getState()')
                    saved_copy = OUT / 'facility/layouts/local/site-local/layouts' / (original['layout']['layoutId'] + '.json')
                    saved_hash = hashlib.sha256(saved_copy.read_bytes()).hexdigest()
                    assert len(original['layout']['placements']) == 827
                    page.locator('#trainFacilityLayoutAuthoring [data-view="3d"]').click(timeout=150000)
                    page.wait_for_function(ADAPTER + '?.getDiagnostics().pendingLoads===0 && ' + ADAPTER + '?.getDiagnostics().assetGroupCount>0', timeout=150000)
                    report['three'] = page.evaluate(ADAPTER + '.getDiagnostics()')
                    assert not report['three']['degraded']
                    assert any(g['representation'] in ('overview', 'detail') and g['prototypeMeshCount'] > 1
                               for g in report['three']['representationGroups'])
                    state = lambda: page.evaluate(ADAPTER + '.getWalkthroughState()')
                    route = next(r for r in original['layout']['routes'] if r['label'] == 'Main Forklift Boulevard')
                    a, b = route['centerline'][0], route['centerline'][-1]
                    spawn = {k: a[k] * .7 + b[k] * .3 for k in ('x', 'y', 'z')}
                    stage('avatar-render')
                    for width, height in [(1440, 900), (900, 700)]:
                        page.set_viewport_size({'width': width, 'height': height})
                        page.evaluate(ADAPTER + '.setWalkthroughCameraMode("third-person")')
                        page.evaluate('(point) => ' + ADAPTER + '.enterWalkthrough({ignoreSelection:true,worldPoint:point})', spawn)
                        page.wait_for_function(ADAPTER + '.getWalkthroughState().locked', timeout=10000)
                        assert state()['avatar']['visible']
                        page.keyboard.down('w')
                        page.wait_for_function(ADAPTER + '.getWalkthroughState().avatar.distanceMeters > .3', timeout=15000)
                        moving = state()
                        assert moving['avatar']['distanceMeters'] > .3
                        assert moving['avatar']['animation'] == 'walk'
                        page.locator('#trainFacilityLayoutAuthoring[data-view-mode="3d"] canvas').first.screenshot(path=str(OUT / f'walking-{width}.png'))
                        page.keyboard.up('w')
                        page.wait_for_function(ADAPTER + '.getWalkthroughState().avatar.animation === "idle"')
                        canvas = page.locator('#trainFacilityLayoutAuthoring[data-view-mode="3d"] canvas').first
                        viewport = canvas.bounding_box()
                        buttons = page.locator('.ip-flw-three-navigation [data-three-command]')
                        button_bottom = viewport['y']
                        for button in buttons.all():
                            rect = button.bounding_box()
                            if not rect: continue
                            assert rect['x'] >= viewport['x'] - 1
                            assert rect['x'] + rect['width'] <= viewport['x'] + viewport['width'] + 1
                            button_bottom = max(button_bottom, rect['y'] + rect['height'])
                        feet = page.evaluate(ADAPTER + '.worldToClient(' + ADAPTER + '.getWalkthroughState().position)')
                        head = page.evaluate('() => {const p=' + ADAPTER + '.getWalkthroughState().position;return ' + ADAPTER + '.worldToClient({...p,y:p.y+1.876});}')
                        hud = page.locator('.ip-flw-walkthrough-hud').bounding_box()
                        assert feet['y'] < hud['y'] - 2, 'Avatar feet must clear the HUD'
                        assert head['y'] > button_bottom + 2, 'Avatar head must clear the toolbar'
                        path = OUT / f'avatar-{width}.png'
                        canvas.screenshot(path=str(path))
                        with Image.open(path) as image:
                            pixels = image.convert('RGB')
                            assert len(pixels.getcolors(pixels.width * pixels.height) or []) > 100
                            torso = pixels.crop((int(pixels.width * .4), int(head['y'] - viewport['y']),
                                                 int(pixels.width * .6), int(feet['y'] - viewport['y'])))
                            vest_pixels = sum(1 for r, g, b in torso.getdata() if r > 70 and g > r * 1.05 and b < r * .6)
                            assert vest_pixels > 25, 'Visible worker vest pixels in projected avatar region'
                        body = state()['position']
                        page.keyboard.press('c')
                        assert state()['cameraMode'] == 'first-person'
                        assert not state()['avatar']['visible']
                        assert state()['position'] == body
                        first = OUT / f'first-person-{width}.png'
                        canvas.screenshot(path=str(first))
                        assert path.read_bytes() != first.read_bytes()
                        page.keyboard.press('c')
                        assert state()['avatar']['visible']
                        report['captures'].append({'width': width, 'height': height, 'moving': moving, 'stopped': state()})
                        goal = {'x': body['x'] + 1, 'z': body['z']}
                        planned = page.evaluate('(goal) => ' + ADAPTER + '.navigateWalkthroughToPoint(goal)', goal)
                        assert planned['ok'] and abs(planned['distance'] - 1) < .0001
                        page.wait_for_function(ADAPTER + '.getWalkthroughState().route.reason === "arrived"', timeout=15000)
                        page.wait_for_function(ADAPTER + '.getWalkthroughState().avatar.animation === "idle"', timeout=5000)
                        before_drone = state()['position']
                        page.keyboard.press('g')
                        assert page.evaluate(ADAPTER + '.getDroneState().active')
                        drone_camera = page.evaluate(ADAPTER + '.getDiagnostics().camera.position')
                        assert abs(drone_camera['x'] - before_drone['x']) < .001
                        assert abs(drone_camera['z'] - before_drone['z']) < .001
                        assert state()['avatar'] is None
                        page.keyboard.press('g')
                        assert state()['avatar']
                        page.evaluate(ADAPTER + '.exitWalkthrough("check")')
                    stage('real-equipment-collision')
                    machine = next(p for p in original['layout']['placements'] if p['assetId'] == 'asset-doosan-dbc130-ii')
                    page.evaluate('(id) => ' + ADAPTER + '.enterWalkthrough({placementId:id})', machine['placementId'])
                    page.wait_for_function(ADAPTER + '.getWalkthroughState().locked', timeout=10000)
                    page.keyboard.down('Shift')
                    page.keyboard.down('w')
                    page.wait_for_function(ADAPTER + '.getWalkthroughState().collisionCount > 3', timeout=30000)
                    page.wait_for_function(ADAPTER + '.getWalkthroughState().avatar.animation === "idle"', timeout=10000)
                    report['collision'] = state()
                    page.keyboard.up('w')
                    page.keyboard.up('Shift')
                    page.screenshot(path=str(OUT / 'machine-collision.png'))
                    page.evaluate(APP + '.workspace._setViewMode("plan")')
                    assert not state()['active'] and state()['avatar'] is None
                    assert hashlib.sha256(saved_copy.read_bytes()).hexdigest() == saved_hash
                    report['isolatedSavedCopyUnchanged'] = True
                    final = page.evaluate(APP + '.session.getState()')
                    for key in ('layout', 'selection', 'history', 'historyCursor', 'baseRevision', 'draftRevision', 'dirty'):
                        assert final[key] == original[key], key
                    assert not report['errors'], report['errors']
                    assert not report['mutations'], report['mutations']
                    report['status'] = 'passed'
                    stage('complete')
                except Exception:
                    page.screenshot(path=str(OUT / 'failure.png'))
                    report['failureState'] = page.evaluate('window.' + APP + '?.workspace?.threeAdapter?.getWalkthroughState()')
                    raise
                finally: browser.close()
        except Exception as error:
            report.update(status='failed', error=repr(error))
            raise
        finally:
            server.terminate()
            try: server.wait(timeout=15)
            except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=10)
            report['backendStopped'] = server.poll() is not None
            report['originalUnchanged'] = hashlib.sha256(Path(source['originalPath']).read_bytes()).hexdigest() == source['originalSha256']
            (OUT / 'result.json').write_text(json.dumps(report, indent=2))
            print(json.dumps({k: report.get(k) for k in ('status','stage','output','error','backendStopped','originalUnchanged')}), flush=True)


if __name__ == '__main__': main()
