"""Verify exact hallway walls and alpha art with the application's Three.js adapter."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import hashlib
import json
from pathlib import Path
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
from tools.add_private_gym_warrior_art import OUT, write


def verify():
    raw = (OUT/'candidate.json').read_bytes()
    candidate = json.loads(raw)
    fixture = json.loads((OUT/'render-fixture.json').read_bytes())
    for p in fixture['layout']['placements']:
        assert p == next(x for x in candidate['placements'] if x['placementId'] == p['placementId'])
    finish = fixture['layout']['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    assert finish['fittedArtworks'] == [a for a in candidate['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'] if a['artworkId'] in fixture['ids']]
    for source in fixture['sources']:
        assert hashlib.sha256((ROOT/source['artifact']).read_bytes()).hexdigest() == source['sha256']
    html = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>html,body,#scene{margin:0;width:100%;height:100%;overflow:hidden}</style>
    <script type="importmap">{"imports":{"three":"/static/vendor/three/0.184.0/build/three.module.min.js"}}</script>
    <script src="/static/facility_layout_avatar.js"></script>
    <script src="/static/walkthrough_camera_settings.js"></script>
    <script src="/static/facility_layout_walls.js"></script>
    <script src="/static/facility_layout_three_adapter.js"></script></head><body><div id="scene"></div>
    <script type="module">
    import * as THREE from 'three';
    import {OrbitControls} from '/static/vendor/three/0.184.0/examples/jsm/controls/OrbitControls.js';
    import {GLTFLoader} from '/static/vendor/three/0.184.0/examples/jsm/loaders/GLTFLoader.js';
    window.fixture=await (await fetch('/fixture.json')).json();
    window.adapter=InspectorProFacilityThree.createThreeAdapter({THREE,OrbitControls,GLTFLoader,
        worldBounds:{minX:0,minZ:-18,maxX:82,maxZ:72,floorY:0},
        assetResolver:r=>r.stage==='overview'?fixture.artifacts[r.assetId]:null});
    adapter.mount(document.getElementById('scene'));
    await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog});window.ready=true;
    </script></body></html>'''

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path in ('/', '/fixture.json'):
                data = html.encode() if self.path == '/' else json.dumps(fixture).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html' if self.path == '/' else 'application/json')
                self.send_header('Content-Length', str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            elif self.path.startswith(('/static/', '/generated/')):
                super().do_GET()
            else:
                self.send_error(404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = dict(status='running', candidateHash=hashlib.sha256(raw).hexdigest(), viewports=[],
        scope='Exact saved wall geometry and candidate art, actual application renderer; focused scene, not full desktop')
    errors = []

    def ready(page, ids=None):
        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0', timeout=60000)
        page.wait_for_function('ids=>ids.every(id=>adapter.getDiagnostics().exteriorArtwork.some(a=>a.artworkId===id&&a.status==="ready"))', arg=fixture['ids'] if ids is None else ids, timeout=60000)
        page.wait_for_timeout(250)

    def camera(page, position, target, fov):
        page.evaluate('([position,target,fov])=>{const v=adapter.getCameraView();Object.assign(v,{position,target,up:{x:0,y:1,z:0},fov,near:.05,far:250});adapter.applyCameraView(v)}',
            [dict(zip(('x','y','z'), position)), dict(zip(('x','y','z'), target)), fov])

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            try:
                for width, height in [(1440, 900), (390, 700)]:
                    page = browser.new_page(viewport=dict(width=width, height=height), device_scale_factor=1)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('requestfailed', lambda request: errors.append(request.url+': '+str(request.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true', timeout=60000)
                    ready(page)
                    captures = []
                    for measured in fixture['measurements']:
                        aid = measured['artworkId']
                        guardian = aid.endswith('spartan')
                        center = measured['centerAlongWall']
                        y = measured['bottomMeters']+measured['heightMeters']/2
                        position = (3.3, y, center) if guardian else (center, y, -.20)
                        target = (.248, y, center) if guardian else (center, y, -2.902)
                        camera(page, position, target, 85 if width < 500 else 65)
                        ready(page)
                        shown = page.screenshot(path=str(OUT/f'{width}-{aid}.png'))
                        diagnostic = page.evaluate('adapter.getDiagnostics()')
                        art = next(a for a in diagnostic['exteriorArtwork'] if a['artworkId'] == aid)
                        assert abs(art['worldWidth']-measured['widthMeters']) < 1e-5
                        assert abs(art['worldHeight']-measured['heightMeters']) < 1e-5
                        assert abs(art['imageFrame']['width']-1) < 1e-5
                        assert abs(art['imageFrame']['height']-1) < 1e-5
                        assert not diagnostic['degraded'] and diagnostic['placementTransformAudit']['transformMismatchCount'] == 0
                        assert all(g['representation'] in ('overview', 'detail') for g in diagnostic['representationGroups'])
                        page.evaluate('''async id=>{const l=structuredClone(fixture.layout);
                            l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks=
                            l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks.filter(a=>a.artworkId!==id);
                            await adapter.setScene({layout:l,assetCatalog:fixture.catalog});}''', aid)
                        ready(page, [i for i in fixture['ids'] if i != aid])
                        hidden = page.screenshot()
                        diff = ImageChops.difference(Image.open(BytesIO(shown)).convert('RGB'), Image.open(BytesIO(hidden)).convert('RGB'))
                        changed = sum(1 for pixel in diff.getdata() if max(pixel) > 25)
                        assert changed > 1000, 'Warrior blank, occluded or facing the wrong way'
                        captures.append(dict(artworkId=aid, changedPixels=changed, frame=art))
                        page.evaluate('async()=>adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog})')
                        ready(page)
                    if width == 1440:
                        camera(page, (35.3, 1.7, -1.2), (.25, 1.5, -1.7), 70)
                        ready(page)
                        page.screenshot(path=str(OUT/'hallway-approach.png'))
                        camera(page, (19, 21, 6), (18, 0, -2), 70)
                        ready(page)
                        page.screenshot(path=str(OUT/'hallway-overview.png'))
                        baseline = {a['artworkId']: a for a in page.evaluate('adapter.getDiagnostics().exteriorArtwork') if a['artworkId'] in fixture['ids']}
                        page.evaluate('''async()=>{const l=structuredClone(fixture.layout);
                            l.placements.forEach(p=>{p.transform.scale*=1.08;p.transform.position.x+=.3});
                            await adapter.setScene({layout:l,assetCatalog:fixture.catalog});}''')
                        ready(page)
                        resized = {a['artworkId']: a for a in page.evaluate('adapter.getDiagnostics().exteriorArtwork') if a['artworkId'] in fixture['ids']}
                        for aid, a in baseline.items():
                            b = resized[aid]
                            assert abs(b['worldWidth']/a['worldWidth']-1.08) < 1e-6
                            assert abs(b['worldHeight']/a['worldHeight']-1.08) < 1e-6
                            assert b['worldPosition'] != a['worldPosition']
                        report['responsiveArtworkVerified'] = True
                    assert not errors, errors
                    report['viewports'].append(dict(width=width, height=height, captures=captures))
                    page.evaluate('adapter.dispose()')
                    page.close()
                report['status'] = 'passed'
            finally:
                browser.close()
    except Exception as error:
        report.update(status='failed', error=str(error), pageErrors=errors)
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        write(OUT/'browser-check.json', report)
    print(json.dumps(dict(status=report['status'], viewports=len(report['viewports']), responsive=True)))


if __name__ == '__main__':
    verify()
