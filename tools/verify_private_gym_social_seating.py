"""Verify the staged furniture in the real renderer and the normal desktop app."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from threading import Thread
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'
from PIL import Image
from playwright.sync_api import sync_playwright
from tools.update_private_gym_social_seating import OUT, LIVING, NEW, TABLE, CHAIR, audit
from tools.build_private_gym import write, STORE, LAYOUT

SHOTS = [
    ('gaming',(9.5,5,-11),(3.6,.4,-6.2)),
    ('reception-detail',(11.1,2.8,10.2),(8.6,.4,7.2)),
    ('reception',(11,8,12.5),(4.7,0,5.6)),
]
ASSETS = [LIVING,TABLE+'-reception-apex',CHAIR+'-reception-apex']


def validate_capture(shown):
    assert len(set(Image.open(BytesIO(shown)).convert('RGB').getdata())) > 1000


def captures(page, adapter, prefix, report):
    page.wait_for_function(adapter+'.getDiagnostics().pendingLoads===0',timeout=120000)
    page.wait_for_timeout(700)
    for name,pos,target in SHOTS:
        page.evaluate('([expr,position,target])=>{const a=eval(expr),v=a.getCameraView();Object.assign(v,{position,target,up:{x:0,y:1,z:0},fov:65,near:.05,far:250});a.applyCameraView(v)}',
            [adapter,dict(zip('xyz',pos)),dict(zip('xyz',target))])
        ids = [LIVING] if name == 'gaming' else ASSETS[1:]
        page.wait_for_function('([expr,ids])=>ids.every(id=>eval(expr).getDiagnostics().representationGroups.some(g=>g.assetId===id&&["overview","detail"].includes(g.representation)))',
            arg=[adapter,ids],timeout=120000)
        page.wait_for_timeout(600)
        shown = page.screenshot(path=str(OUT/(prefix+'-'+name+'.png')),timeout=20000)
        validate_capture(shown)
        d = page.evaluate(adapter+'.getDiagnostics()')
        assert not d['warnings'],d['warnings']
        assert d['placementTransformAudit']['transformMismatchCount'] == 0
        report['captures'].append(dict(name=prefix+'-'+name,sha256=hashlib.sha256(shown).hexdigest()))


def staged():
    fixture = json.loads((OUT/'render-fixture.json').read_bytes())
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
    const fixture=await(await fetch('/fixture.json')).json();
    window.adapter=InspectorProFacilityThree.createThreeAdapter({THREE,OrbitControls,GLTFLoader,
      worldBounds:{minX:0,minZ:-18,maxX:82,maxZ:72,floorY:0},
      assetResolver:r=>r.stage==='overview'?fixture.artifacts[r.assetId]:null});
    adapter.mount(document.getElementById('scene'));
    await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog});window.ready=true;
    </script></body></html>'''
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
        def do_GET(self):
            if self.path in ('/','/fixture.json'):
                data = html.encode() if self.path == '/' else json.dumps(fixture).encode()
                self.send_response(200)
                self.send_header('Content-Type','text/html' if self.path == '/' else 'application/json')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers();self.wfile.write(data)
            elif self.path.startswith('/staged/generated/'):
                self.path = '/.runtime/private-gym-social-seating-20261010/staged-project/'+self.path.removeprefix('/staged/')
                super().do_GET()
            elif self.path.startswith(('/static/','/generated/')):
                super().do_GET()
            else:
                self.send_error(404)
    server = ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    thread = Thread(target=server.serve_forever,daemon=True);thread.start()
    report = dict(status='running',candidateSha256=hashlib.sha256((OUT/'candidate.json').read_bytes()).hexdigest(),captures=[])
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
            try:
                for width,height in [(1440,900),(390,700)]:
                    page = browser.new_page(viewport=dict(width=width,height=height))
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('requestfailed',lambda r:errors.append(r.url+': '+str(r.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true',timeout=60000)
                    captures(page,'window.adapter',str(width),report)
                    page.evaluate('adapter.dispose()');page.close()
                assert not errors,errors
                report['status'] = 'passed'
            finally:
                browser.close()
    except Exception as exc:
        report.update(status='failed',error=str(exc),errors=errors)
        raise
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        write(OUT/'renderer-check.json',report)
    print(json.dumps(dict(status=report['status'],captures=len(report['captures']))))


def desktop():
    app = 'window._trainFacilityLayoutAuthoringApp'
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw = target.read_bytes()
    saved = json.loads(raw)
    report = dict(status='running',captures=[])
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        deadline = time.monotonic()+120
        page = None
        while page is None and time.monotonic()<deadline:
            page = next((p for c in browser.contexts for p in c.pages if p.url.startswith('http://127.0.0.1:8480/')),None)
            if page is None: time.sleep(.5)
        assert page is not None
        page.wait_for_function(app+'?.session?.getState().loaded',timeout=120000)
        state = page.evaluate(app+'.session.getState()')
        assert state['layout'] == saved and not state['dirty']
        catalog = {a['assetId']:a for a in page.evaluate(app+'.workspace.assetCatalog.map(a=>a.source)')}
        report['checks'] = audit(json.loads((OUT/'before.json').read_bytes()),saved,catalog)
        page.evaluate(app+".workspace._setViewMode('3d')")
        adapter = app+'.workspace.threeAdapter'
        page.evaluate(adapter+".exitWalkthrough('social-seating-review')")
        page.wait_for_function('ids=>ids.every(id=>'+adapter+'.getDiagnostics().representationGroups.some(g=>g.assetId===id))',arg=ASSETS,timeout=120000)
        captures(page,adapter,'desktop',report)
        d = page.evaluate(adapter+'.getDiagnostics()')
        groups = [g for g in d['representationGroups'] if g['assetId'] in ASSETS]
        assert set(next(g for g in groups if g['assetId']==LIVING)['placementIds']) == {NEW,'pl-gym-reception-living-room-1'}
        hashes = {}
        for aid in ASSETS:
            group = next(g for g in groups if g['assetId']==aid)
            assert group['assetDefinitionRevision'] == catalog[aid]['assetDefinitionRevision']
            url = catalog[aid]['overview']['path']
            served = page.evaluate('async u=>{const r=await fetch(u);if(!r.ok)throw Error(r.status);return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await r.arrayBuffer())),v=>v.toString(16).padStart(2,"0")).join("")}',url)
            assert served == hashlib.sha256((ROOT/url.lstrip('/')).read_bytes()).hexdigest()
            hashes[aid] = served
        final = page.evaluate(app+'.session.getState()')
        assert final['layout'] == saved and not final['dirty'] and final['selection'] == state['selection']
        assert target.read_bytes() == raw
        report.update(status='passed',groups=groups,servedAssetHashes=hashes,savedBytesUnchanged=True)
        write(OUT/'desktop-check.json',report)
        print(json.dumps(dict(status='passed',captures=len(report['captures']),saved=True)))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true')
    args = parser.parse_args()
    desktop() if args.desktop else staged()
