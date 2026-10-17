"""Actual manual-layout operator activity in the shared desktop frontend; no provider or Save."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime' / ('operator-motion-' + time.strftime('%Y%m%d-%H%M%S'))
PORT = 8496
BASE = f'http://127.0.0.1:{PORT}'
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
APP = '_trainFacilityLayoutAuthoringApp'
W = APP + '.workspace'
A = W + '.threeAdapter'


def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', PORT))
    subprocess.run([sys.executable, 'desktop/tools/prepare-application-check.py', '--destination', str(OUT), '--port', str(PORT)],
                   cwd=ROOT, check=True, creationflags=HIDDEN)
    source = json.loads((OUT / 'application-check-source.json').read_text())
    report = {'status': 'running', 'errors': [], 'writes': [], 'captures': [], 'motionCache': 'cold'}
    if '--existing-motion-cache' in sys.argv:
        import shutil
        cache = ROOT / '.runtime/facility-layout/layouts/.derived/activity-scenarios'
        target = OUT / 'facility/layouts/.derived/activity-scenarios'
        shutil.copytree(cache, target)
        report['motionCache'] = 'existing_revision_bound_artifacts'
        report['cacheFiles'] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in cache.glob('*.json')}
    def stage(name):
        report['stage'] = name
        (OUT / 'result.json').write_text(json.dumps(report, indent=2))
        try: print(name, flush=True)
        except OSError: pass
    env = dict(os.environ, INSPECTORPRO_FACILITY_LAYOUT_ROOT=str(OUT / 'facility'),
               INSPECTORPRO_INDUSTRIAL_ASSET_LIBRARY='1', INSPECTORPRO_FACILITY_MOTION_PROTOTYPE='1')
    for flag in ['VIEWER_V2', 'MANUAL_EDIT', 'CONSTRAINTS', 'ROUTING']:
        env['INSPECTORPRO_FACILITY_LAYOUT_' + flag] = '1'
    with (OUT / 'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable, '-m', 'uvicorn', 'server:app', '--host', '127.0.0.1', '--port', str(PORT)],
                                  cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=HIDDEN)
        try:
            stage('backend-start')
            deadline = time.monotonic() + 120
            while True:
                try:
                    urllib.request.urlopen(BASE + '/api/facility-layout-bootstrap', timeout=3).close()
                    break
                except Exception:
                    if server.poll() is not None or time.monotonic() > deadline: raise RuntimeError('Backend startup failed')
                    time.sleep(.5)
            with sync_playwright() as p:
                browser = p.chromium.launch(headless=True)
                page = browser.new_page(viewport={'width': 1440, 'height': 900})
                page.set_default_timeout(120000)
                page.on('pageerror', lambda e: report['errors'].append(str(e)))
                page.on('console', lambda e: report['errors'].append(e.text) if 'Shader Error' in e.text else None)
                page.on('request', lambda r: report['writes'].append({'url': r.url, 'method': r.method})
                        if r.method in ('POST', 'PUT', 'DELETE') and '/api/facility-layouts/' in r.url else None)
                page.route('**/api/voice/synthesize', lambda r: r.fulfill(status=503, body='Not part of motion check'))
                def capture(name):
                    page.screenshot(path=str(OUT / (name + '.png')))
                    with Image.open(OUT / (name + '.png')) as image:
                        assert len(image.convert('RGB').getcolors(image.width * image.height) or []) > 100
                    report['captures'].append(name)
                state = lambda: page.evaluate(A + '.activity.getState()')
                def seek(seconds):
                    page.evaluate('(t)=>{const a=' + A + ';a.activity.pause();a.activity.seek(t);}', seconds)
                    page.wait_for_function('!' + A + '.getDiagnostics().demandRendering.pendingFrame')
                    return state()
                try:
                    stage('manual-load')
                    page.goto(BASE + '/?facilityLayoutId=fl-reference-manual-20260812', wait_until='domcontentloaded')
                    page.get_by_role('tab', name='Workflows', exact=True).click()
                    page.select_option('#trainingTypeRibbonSelect', 'facility_layout')
                    page.wait_for_function('window.' + APP + '?.session.getState().loaded')
                    original = page.evaluate(APP + '.session.getState()')
                    assert len(original['layout']['placements']) == 827
                    saved = OUT / 'facility/layouts/local/site-local/layouts' / (original['layout']['layoutId'] + '.json')
                    saved_hash = hashlib.sha256(saved.read_bytes()).hexdigest()
                    page.locator('#trainFacilityLayoutAuthoring [data-view="3d"]').click()
                    page.wait_for_function(A + '.getDiagnostics().pendingLoads===0 && ' + A + '.getDiagnostics().assetGroupCount>0', timeout=240000)
                    diagnostics = page.evaluate(A + '.getDiagnostics()')
                    assert not diagnostics['degraded']
                    operator = next(g for g in diagnostics['representationGroups'] if g['assetId'] == 'asset-operator')
                    assert operator['representation'] == 'operator-avatar'
                    assert operator['instanced'] and len(operator['placementIds']) == 20
                    report['standingOperators'] = operator
                    capture('standing-manual-layout')
                    stage('prepare-existing-complete-motion')
                    page.evaluate('''()=>{window.__operatorMotion = {};''' + W + '''.startActivityPlayback({
                        preset:'reference_complete_navigation',prototypeMode:true,maximumActors:23
                    }).then(r=>window.__operatorMotion={done:true,result:r})
                      .catch(e=>window.__operatorMotion={done:true,error:e.message,code:e.code});}''')
                    page.wait_for_function('window.__operatorMotion.done', timeout=600000)
                    result = page.evaluate('window.__operatorMotion')
                    assert 'error' not in result, result
                    report['initialActivity'] = seek(3.17)
                    actors = report['initialActivity']['actors']
                    operators = [a for a in actors if a['actorType'] == 'operator']
                    vehicles = [a for a in actors if a['actorType'] == 'vehicle']
                    assert len(operators) >= 2 and len(vehicles) >= 1
                    assert all(a['visualSource'] == 'animated-operator-avatar' and not a['exactCatalogVisual'] for a in operators)
                    assert all(a['exactCatalogVisual'] and a['visualSource'] == 'catalog-glb' for a in vehicles)
                    assert all(a['sourcePlacementSuppressed'] for a in actors)
                    assert not report['initialActivity']['duplicateVisiblePlacementIds']
                    moving = next(a for a in operators if a['visible'] and a['avatar']['animation'] == 'walk' and abs(a['avatar']['leftHip']) > .01)
                    actor_id = moving['actorId']
                    stage('walking-closeup')
                    page.evaluate('(p)=>{const a=' + A + ',v=a.getCameraView();v.position={x:p.x+3,y:p.y+2.6,z:p.z+4};v.target={x:p.x,y:p.y+.9,z:p.z};a.applyCameraView(v);}',
                                  dict(moving['pose'], y=0))
                    page.wait_for_function('!' + A + '.getDiagnostics().demandRendering.pendingFrame')
                    capture('walking-a')
                    frame_b = seek(3.51)
                    b = next(a for a in frame_b['actors'] if a['actorId'] == actor_id)
                    assert b['avatar']['phase'] != moving['avatar']['phase']
                    capture('walking-b')
                    with Image.open(OUT / 'walking-a.png') as x, Image.open(OUT / 'walking-b.png') as y:
                        delta = ImageChops.difference(x.convert('RGB'), y.convert('RGB'))
                        report['changedPixels'] = sum(1 for pixel in delta.getdata() if max(pixel) > 12)
                        assert report['changedPixels'] > 100
                    restored = seek(3.17)
                    assert next(a for a in restored['actors'] if a['actorId'] == actor_id)['avatar'] == moving['avatar']
                    stage('real-play-pause')
                    page.locator('[data-motion-action="toggle-play"]').click()
                    page.wait_for_function(A + '.activity.getState().elapsedSeconds>4')
                    page.locator('[data-motion-action="toggle-play"]').click()
                    frozen = state()
                    page.wait_for_timeout(500)
                    assert state()['actors'] == frozen['actors']
                    report['pausedActivity'] = frozen
                    stage('plan-and-narrow-view')
                    page.locator('#trainFacilityLayoutAuthoring [data-view="plan"]').click()
                    capture('plan-motion')
                    page.locator('#trainFacilityLayoutAuthoring [data-view="3d"]').click()
                    page.set_viewport_size({'width': 900, 'height': 700})
                    capture('narrow-motion')
                    page.locator('[data-motion-action="close"]').click()
                    assert not state()['loaded']
                    assert not state()['visibleSourcePlacementIds']
                    final = page.evaluate(APP + '.session.getState()')
                    for key in ('layout', 'history', 'historyCursor', 'baseRevision', 'draftRevision', 'dirty'):
                        assert final[key] == original[key], key
                    assert hashlib.sha256(saved.read_bytes()).hexdigest() == saved_hash
                    report['savedCopyUnchanged'] = True
                    report['finalActivity'] = state()
                    assert not report['errors'], report['errors']
                    report['status'] = 'passed'; stage('complete')
                except Exception as error:
                    report.update(status='failed', error=repr(error))
                    try: capture('failure')
                    except Exception: pass
                    raise
                finally:
                    browser.close()
        finally:
            server.terminate()
            try: server.wait(timeout=15)
            except subprocess.TimeoutExpired: server.kill(); server.wait(timeout=10)
            report['backendStopped'] = server.poll() is not None
            report['manualLayoutUnchanged'] = hashlib.sha256(Path(source['originalPath']).read_bytes()).hexdigest() == source['originalSha256']
            (OUT / 'result.json').write_text(json.dumps(report, indent=2))
            try: print(str(OUT), flush=True)
            except OSError: pass


if __name__ == '__main__': main()
