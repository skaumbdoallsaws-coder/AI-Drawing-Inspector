"""Render exact outdoor wall assets with the application adapter; no store writes."""
from copy import deepcopy
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
from tools.add_private_gym_outdoor_art import OUT, SPECS, write


def verify():
    raw = (OUT/'candidate.json').read_bytes()
    fixture = json.loads((OUT/'render-fixture.json').read_bytes())
    candidate = json.loads(raw)
    for p in fixture['layout']['placements']:
        assert p == next(x for x in candidate['placements'] if x['placementId'] == p['placementId'])
    assert fixture['layout']['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'] == [
        a for a in candidate['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks']
        if a['artworkId'] in fixture['ids']]
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
        assetResolver:request=>request.stage==='overview'?fixture.artifacts[request.assetId]:null});
    adapter.mount(document.getElementById('scene'));
    await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog});
    window.ready=true;
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
        scope='Focused actual wall meshes, exact transforms and PNGs, using InspectorPro Three.js adapter')
    errors = []
    def ready(page, artwork=True):
        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0', timeout=60000)
        if artwork:
            page.wait_for_function('fixture.ids.every(id=>adapter.getDiagnostics().exteriorArtwork.some(a=>a.artworkId===id&&a.status==="ready"))', timeout=60000)
        page.wait_for_timeout(400)

    def camera(page, p, t):
        page.evaluate('([p,t])=>{const v=adapter.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov:55,near:.1,far:400});adapter.applyCameraView(v)}',
            [dict(zip(('x','y','z'),p)), dict(zip(('x','y','z'),t))])
        ready(page)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            try:
                for width, height in [(1440, 900), (390, 700)]:
                    page = browser.new_page(viewport=dict(width=width, height=height), device_scale_factor=1)
                    page.on('pageerror', lambda error: errors.append(str(error)))
                    page.on('requestfailed', lambda request: errors.append(request.url + ': ' + str(request.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true', timeout=60000)
                    factor = max(1, 1.6/(width/height))
                    captures = []
                    for spec, p, t in [
                        (SPECS[0], (64, 3.5, 50.45), (41.85, 3.1, 50.45)),
                        (SPECS[1], (71.5, 3, 57), (71.5, 2.75, 36.15)),
                    ]:
                        position = [t[i]+(p[i]-t[i])*factor for i in range(3)]
                        camera(page, position, t)
                        shown = page.screenshot(path=str(OUT/f'{width}-{spec["id"]}.png'))
                        diagnostic = page.evaluate('adapter.getDiagnostics()')
                        art = next(a for a in diagnostic['exteriorArtwork'] if a['artworkId'] == spec['id'])
                        assert abs(art['worldWidth']-spec['width']*.98) < 1e-5
                        assert abs(art['worldHeight']-spec['height']*.98) < 1e-5
                        assert abs(art['imageFrame']['width']-1) < 1e-6
                        assert not diagnostic['degraded'] and diagnostic['placementTransformAudit']['transformMismatchCount'] == 0
                        assert all(g['representation'] in ('overview', 'detail') for g in diagnostic['representationGroups'])
                        page.evaluate('''async()=>{const l=structuredClone(fixture.layout);
                            l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks=[];
                            await adapter.setScene({layout:l,assetCatalog:fixture.catalog});}''')
                        ready(page, False)
                        hidden = page.screenshot()
                        diff = ImageChops.difference(Image.open(BytesIO(shown)).convert('RGB'), Image.open(BytesIO(hidden)).convert('RGB'))
                        changed = sum(1 for pixel in diff.getdata() if max(pixel) > 25)
                        assert changed > 500, 'Mural is blank, behind the wall, or facing away'
                        captures.append(dict(artworkId=spec['id'], changedPixels=changed, frame=art))
                        page.evaluate('async()=>{await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog})}')
                        ready(page)
                    if width == 1440:
                        camera(page, (88, 21, 80), (57, 1.8, 47))
                        page.screenshot(path=str(OUT/'outdoor-murals-context.png'))
                        baseline = page.evaluate('adapter.getDiagnostics().exteriorArtwork')
                        page.evaluate('''async()=>{const l=structuredClone(fixture.layout);
                            l.placements.forEach(p=>{p.transform.scale*=1.1;p.transform.position.x+=1});
                            await adapter.setScene({layout:l,assetCatalog:fixture.catalog});}''')
                        ready(page)
                        resized = page.evaluate('adapter.getDiagnostics().exteriorArtwork')
                        for a, b in zip(baseline, resized):
                            assert a['artworkId'] == b['artworkId']
                            assert abs(b['worldWidth']/a['worldWidth']-1.1) < 1e-6
                            assert abs(b['worldHeight']/a['worldHeight']-1.1) < 1e-6
                            assert b['worldPosition']['x'] > a['worldPosition']['x']+.9
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
