"""Check staged patio meshes in InspectorPro's actual Three.js renderer."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image
from playwright.sync_api import sync_playwright
from tools.style_private_gym_patio import OUT, TARGETS, write


def verify():
    raw = (OUT/'candidate.json').read_bytes()
    candidate = json.loads(raw)
    fixture = json.loads((OUT/'render-fixture.json').read_bytes())
    for p in fixture['layout']['placements']:
        assert p == next(a for a in candidate['placements'] if a['placementId'] == p['placementId'])
    materials = json.loads((OUT/'report.json').read_bytes())
    for relative, digest in materials['variantHashes'].items():
        assert hashlib.sha256((OUT/'staged-project'/relative).read_bytes()).hexdigest() == digest
    html = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
    <style>html,body,#scene{margin:0;width:100%;height:100%;overflow:hidden}</style>
    <script type="importmap">{"imports":{"three":"/static/vendor/three/0.184.0/build/three.module.min.js"}}</script>
    <script src="/static/facility_layout_avatar.js"></script><script src="/static/walkthrough_camera_settings.js"></script>
    <script src="/static/facility_layout_walls.js"></script><script src="/static/facility_layout_three_adapter.js"></script>
    </head><body><div id="scene"></div><script type="module">
    import * as THREE from 'three';
    import {OrbitControls} from '/static/vendor/three/0.184.0/examples/jsm/controls/OrbitControls.js';
    import {GLTFLoader} from '/static/vendor/three/0.184.0/examples/jsm/loaders/GLTFLoader.js';
    window.fixture=await(await fetch('/fixture.json')).json();
    window.adapter=InspectorProFacilityThree.createThreeAdapter({THREE,OrbitControls,GLTFLoader,
      worldBounds:{minX:68,minZ:62,maxX:82,maxZ:72,floorY:0},
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
            else:
                super().do_GET()

        def translate_path(self, path):
            original = Path(super().translate_path(path))
            relative = original.relative_to(ROOT)
            staged = OUT/'staged-project'/relative
            return str(staged if staged.is_file() else original)

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = dict(status='running', candidateHash=hashlib.sha256(raw).hexdigest(), captures=[],
                  scope='Actual application renderer with exact staged patio meshes and transforms')
    errors = []
    shots = [
        ('pergola', (77, 4.6, 74), (73, 1.4, 68)),
        ('picnic', (81.5, 2.4, 71.4), (78.8, .55, 68.5)),
        ('drinks', (74.7, 1.65, 70.2), (73, .75, 68)),
        ('grill', (82, 2.3, 61.3), (78.8, .8, 63.8)),
        ('patio', (87, 9, 79), (75, .6, 67)),
    ]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            try:
                for width, height in [(1440, 900), (390, 700)]:
                    page = browser.new_page(viewport=dict(width=width, height=height), device_scale_factor=1)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('requestfailed', lambda r: errors.append(r.url+': '+str(r.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true', timeout=60000)
                    for name, p, t in shots:
                        factor = max(1, 1.2/(width/height))
                        position = [t[i]+(p[i]-t[i])*factor for i in range(3)]
                        page.evaluate('([p,t])=>{const v=adapter.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov:50,near:.05,far:300});adapter.applyCameraView(v)}',
                                      [dict(zip('xyz', position)), dict(zip('xyz', t))])
                        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0', timeout=60000)
                        page.wait_for_timeout(400)
                        diagnostic = page.evaluate('adapter.getDiagnostics()')
                        assert not diagnostic['degraded']
                        assert diagnostic['placementTransformAudit']['transformMismatchCount'] == 0
                        groups = diagnostic['representationGroups']
                        assert len(groups) == len(fixture['artifacts'])
                        assert all(g['representation'] in ('overview', 'detail') for g in groups)
                        png = page.screenshot(path=str(OUT/f'{width}-{name}.png'))
                        pixels = list(Image.open(BytesIO(png)).convert('RGB').getdata())
                        gold = sum(r > 60 and r > g*1.15 and g > b*1.35 for r, g, b in pixels)
                        assert gold > 80, (name, width, gold)
                        assert len(set(pixels)) > 100, 'Blank viewport'
                        report['captures'].append(dict(name=name, width=width, height=height, goldPixels=gold,
                            actualMeshGroups=len(groups), transformMismatchCount=0))
                    assert not errors, errors
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
    print(json.dumps(dict(status=report['status'], captures=len(report['captures']))))


if __name__ == '__main__':
    verify()
