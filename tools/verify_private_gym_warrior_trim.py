"""Render the staged gold wall edges with the actual application Three.js adapter."""
from copy import deepcopy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import argparse
import hashlib
import json
from pathlib import Path
import sys
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
from tools.trim_private_gym_warrior_walls import OUT, TARGETS, write
from tools.apex_equipment_materials import np


def verify(office=False):
    raw = (OUT/'candidate.json').read_bytes()
    candidate = json.loads(raw)
    fixture = json.loads((OUT/'render-fixture.json').read_bytes())
    for p in fixture['layout']['placements']:
        assert p == next(x for x in candidate['placements'] if x['placementId'] == p['placementId'])
    for relative, digest in json.loads((OUT/'report.json').read_bytes())['variantHashes'].items():
        assert hashlib.sha256((OUT/'staged-project'/relative).read_bytes()).hexdigest() == digest
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
    window.fixture=await(await fetch('/fixture.json')).json();
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
                content = html.encode() if self.path == '/' else json.dumps(fixture).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'text/html' if self.path == '/' else 'application/json')
                self.send_header('Content-Length', str(len(content)))
                self.end_headers()
                self.wfile.write(content)
            elif self.path.startswith(('/static/', '/generated/')):
                super().do_GET()
            else:
                self.send_error(404)

        def translate_path(self, path):
            original = Path(super().translate_path(path))
            staged = OUT/'staged-project'/original.relative_to(ROOT)
            return str(staged if staged.is_file() else original)

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    report = dict(status='running', candidateHash=hashlib.sha256(raw).hexdigest(), captures=[],
        scope='Exact staged wall meshes and art; actual application renderer, not full desktop')
    errors = []

    def ready(page, art=True):
        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0', timeout=60000)
        if art:
            page.wait_for_function('ids=>ids.every(id=>adapter.getDiagnostics().exteriorArtwork.some(a=>a.artworkId===id&&a.status==="ready"))', arg=fixture['ids'], timeout=60000)
        page.wait_for_timeout(250)

    def camera(page, position, target):
        page.evaluate('([p,t])=>{const v=adapter.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov:65,near:.05,far:250});adapter.applyCameraView(v)}',
            [dict(zip('xyz', position)), dict(zip('xyz', target))])

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            try:
                for width, height in [(1440,900), (390,700)]:
                    page = browser.new_page(viewport=dict(width=width,height=height), device_scale_factor=1)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.on('requestfailed', lambda r: errors.append(r.url+': '+str(r.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true', timeout=60000)
                    ready(page)
                    camera(page, (35,3,-9.7) if office else (21,1.7,-.45),
                        (32.8,1,-4.5) if office else (16,1.5,-2.95))
                    ready(page)
                    overview = page.screenshot(path=str(OUT/f'{width}-hallway.png'))
                    if office and width == 390:
                        pixels = np.asarray(Image.open(BytesIO(overview)).convert('RGB')).astype(float)
                        assert np.count_nonzero((pixels[:,:,0]>20)&(pixels[:,:,0]>pixels[:,:,1]*1.15)&
                            (pixels[:,:,1]>pixels[:,:,2]*1.35)) > 80, 'Missing mobile office trim'
                        assert len(np.unique(pixels.reshape((-1,3)),axis=0)) > 20, 'Blank mobile canvas'
                        report['captures'].append(dict(width=width,height=height,officeContextNonblank=True))
                        page.evaluate('adapter.dispose()')
                        page.close()
                        continue
                    baseline_art = page.evaluate('adapter.getDiagnostics().exteriorArtwork')
                    for pid, face in TARGETS.items():
                        placement = next(p for p in fixture['layout']['placements'] if p['placementId'] == pid)
                        asset = next(a for a in fixture['catalog'] if a['assetId'] == placement['assetId'])
                        aabb = asset['definition']['geometry']['aabb']
                        p = placement['transform']['position']
                        x_face = face.endswith('_x')
                        sign = 1 if face.startswith('positive') else -1
                        tangent = 'z' if x_face else 'x'
                        wall_width = aabb['maximum'][tangent]-aabb['minimum'][tangent]
                        distance = max(3.4, wall_width/1.1/(width/height))
                        target = (p['x'], 1.6, p['z'])
                        position = (p['x']+sign*distance,1.6,p['z']) if x_face else (p['x'],1.6,p['z']+sign*distance)
                        # Isolate this exact wall only for edge-pixel comparison; the hallway above tests context.
                        isolated = deepcopy(fixture['layout'])
                        isolated['placements'] = [placement]
                        isolated['extensions'].pop('facilityPerimeterWalls')
                        page.evaluate('async layout=>adapter.setScene({layout,assetCatalog:fixture.catalog})', isolated)
                        camera(page, position, target)
                        ready(page, False)
                        shown = page.screenshot(path=str(OUT/f'{width}-{pid}.png'))
                        diagnostic = page.evaluate('adapter.getDiagnostics()')
                        assert not diagnostic['degraded']
                        assert diagnostic['placementTransformAudit']['transformMismatchCount'] == 0
                        assert all(g['representation'] in ('overview','detail') for g in diagnostic['representationGroups'])
                        isolated['placements'] = [next(p for p in fixture['originalPlacements'] if p['placementId'] == pid)]
                        page.evaluate('async layout=>adapter.setScene({layout,assetCatalog:fixture.catalog})', isolated)
                        ready(page, False)
                        original = page.screenshot()
                        after = Image.open(BytesIO(shown)).convert('RGB')
                        before = Image.open(BytesIO(original)).convert('RGB')
                        diff = ImageChops.difference(after,before)
                        # The south-facing office wall is shaded by the existing scene lighting.
                        # Count gold-hued changed pixels, not unrelated bright floor markings.
                        pixels = np.asarray(after).astype(float)
                        changed_mask = np.max(np.asarray(diff),axis=2)>15
                        gold = int(np.count_nonzero((pixels[:,:,0]>(20 if office else 60))&
                            (pixels[:,:,0]>pixels[:,:,1]*1.15)&(pixels[:,:,1]>pixels[:,:,2]*1.35)&changed_mask))
                        changed = int(np.count_nonzero(changed_mask))
                        assert gold > 80 and changed > 80, (pid,width,gold,changed)
                        assert len(set(after.getdata())) > 20, 'Blank canvas'
                        report['captures'].append(dict(placementId=pid,width=width,height=height,
                            goldPixels=gold,changedPixels=changed))
                        if office:
                            reverse = (p['x']-sign*distance,1.6,p['z']) if x_face else (p['x'],1.6,p['z']-sign*distance)
                            camera(page, reverse, target)
                            ready(page, False)
                            original_reverse = page.screenshot()
                            isolated['placements'] = [placement]
                            page.evaluate('async layout=>adapter.setScene({layout,assetCatalog:fixture.catalog})', isolated)
                            ready(page, False)
                            revised_reverse = page.screenshot(path=str(OUT/f'{width}-{pid}-reverse.png'))
                            diff = ImageChops.difference(Image.open(BytesIO(original_reverse)).convert('RGB'),
                                Image.open(BytesIO(revised_reverse)).convert('RGB'))
                            reverse_changed = int(np.count_nonzero(np.max(np.asarray(diff),axis=2)>15))
                            assert reverse_changed == 0, ('Reverse wall face changed',pid,reverse_changed)
                            report['captures'][-1]['reverseChangedPixels'] = reverse_changed
                    page.evaluate('async()=>adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog})')
                    ready(page)
                    assert page.evaluate('adapter.getDiagnostics().exteriorArtwork') == baseline_art
                    camera(page, (31.3,2.1,-4.6) if office else (35,1.6,-.8),
                        (33,1.4,-10.8) if office else (.3,1.6,-1.8))
                    ready(page)
                    page.screenshot(path=str(OUT/f'{width}-hallway-approach.png'))
                    assert not errors, errors
                    page.evaluate('adapter.dispose()')
                    page.close()
                report.update(status='passed', artworkAttachmentsUnchanged=True)
            finally:
                browser.close()
    except Exception as error:
        report.update(status='failed',error=str(error),pageErrors=errors)
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        write(OUT/'browser-check.json',report)
    print(json.dumps(dict(status=report['status'], captures=len(report['captures']))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--office', action='store_true')
    args = parser.parse_args()
    if args.office:
        from tools.trim_private_gym_office_walls import OUT, TARGETS
    verify(office=args.office)
