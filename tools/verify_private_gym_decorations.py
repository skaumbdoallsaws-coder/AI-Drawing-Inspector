"""Render the exact staged outdoor decorations before publishing the saved gym."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image
from playwright.sync_api import sync_playwright
from tools.import_private_gym_decorations import OUT
from tools.build_private_gym import write

SHOTS = [
    ('bull',(44.5,2.6,37.2),(48.2,.8,41.45)),
    ('ducati-front',(74.6,1.8,48.3),(78,.5,51.5)),
    ('ducati-rear',(81.3,1.65,54.4),(78,.5,51.5)),
    ('dog',(71.6,1.65,65.5),(69.2,.3,63.2)),
    ('outdoor',(95,36,89),(63,0,56)),
]


def verify():
    raw = (OUT/'candidate.json').read_bytes()
    candidate = json.loads(raw)
    fixture = json.loads((OUT/'render-fixture.json').read_bytes())
    for placement in fixture['layout']['placements']:
        assert placement == next(p for p in candidate['placements'] if p['placementId']==placement['placementId'])
    for relative,digest in json.loads((OUT/'report.json').read_bytes())['assetHashes'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest
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
      worldBounds:{minX:44,minZ:40,maxX:82,maxZ:72,floorY:0},
      assetResolver:r=>r.stage==='overview'?fixture.artifacts[r.assetId]:null});
    adapter.mount(document.getElementById('scene'));
    await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog});window.ready=true;
    </script></body></html>'''

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):
            pass

        def do_GET(self):
            if self.path in ('/','/fixture.json'):
                data = html.encode() if self.path=='/' else json.dumps(fixture).encode()
                self.send_response(200)
                self.send_header('Content-Type','text/html' if self.path=='/' else 'application/json')
                self.send_header('Content-Length',str(len(data)))
                self.end_headers()
                self.wfile.write(data)
            else:
                super().do_GET()

    server = ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    thread = Thread(target=server.serve_forever,daemon=True)
    thread.start()
    report = dict(status='running',candidateSha256=hashlib.sha256(raw).hexdigest(),captures=[],
                  scope='InspectorPro Three.js renderer with exact staged meshes and transforms')
    errors=[]
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
            try:
                for width,height in [(1440,900),(390,700)]:
                    page = browser.new_page(viewport=dict(width=width,height=height),device_scale_factor=1)
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('requestfailed',lambda r:errors.append(r.url+': '+str(r.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true',timeout=120000)
                    for name,p,t in SHOTS:
                        # Pulling the small patio sculpture's camera back would cross the pergola roof.
                        factor=1 if name=='dog' else max(1,1.2/(width/height))
                        position=[t[i]+(p[i]-t[i])*factor for i in range(3)]
                        page.evaluate('([p,t])=>{const v=adapter.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov:50,near:.05,far:300});adapter.applyCameraView(v)}',
                                      [dict(zip('xyz',position)),dict(zip('xyz',t))])
                        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0',timeout=120000)
                        page.wait_for_timeout(600)
                        diagnostic=page.evaluate('adapter.getDiagnostics()')
                        assert not diagnostic['degraded']
                        assert diagnostic['placementTransformAudit']['transformMismatchCount']==0
                        groups=diagnostic['representationGroups']
                        assert len(groups)==len(fixture['artifacts'])
                        assert all(g['representation'] in ('overview','detail') for g in groups)
                        png=page.screenshot(path=str(OUT/f'{width}-{name}.png'))
                        pixels=list(Image.open(BytesIO(png)).convert('RGB').getdata())
                        gold=sum(r>60 and r>g*1.15 and g>b*1.35 for r,g,b in pixels)
                        assert gold>80,(name,width,gold)
                        assert len(set(pixels))>100,'Blank viewport'
                        report['captures'].append(dict(name=name,width=width,height=height,goldPixels=gold,
                            actualMeshGroups=len(groups),transformMismatchCount=0))
                    assert not errors,errors
                    page.evaluate('adapter.dispose()')
                    page.close()
                report['status']='passed'
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
    print(json.dumps(dict(status=report['status'],captures=len(report['captures']))))


def desktop():
    from tools.build_private_gym import STORE,LAYOUT
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=path.read_bytes()
    saved=json.loads(raw)
    assert saved==json.loads((OUT/'saved.json').read_bytes())
    ids=['asset-gym-decoration-'+k for k in ('bull','dog','ducati')]
    app='window._trainFacilityLayoutAuthoringApp'
    adapter=app+'.workspace.threeAdapter'
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        page=next(p for c in browser.contexts for p in c.pages if p.url.startswith('http://127.0.0.1:8480/'))
        page.wait_for_function(app+'?.session?.getState().loaded===true',timeout=120000)
        state=page.evaluate(app+'.session.getState()')
        assert not state['dirty'] and state['layout']==saved,'Desktop has unsaved or stale layout data'
        page.evaluate(app+".workspace._setViewMode('3d')")
        page.evaluate(adapter+".exitWalkthrough('decorations-review')")
        result=dict(status='running',captures=[],meshGroups=[],servedAssetHashes={})
        for name,p,t in SHOTS:
            page.evaluate('([expr,p,t])=>{const a=eval(expr),v=a.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov:50,near:.05,far:300});a.applyCameraView(v)}',
                          [adapter,dict(zip('xyz',p)),dict(zip('xyz',t))])
            page.wait_for_function('([expr,ids])=>{const d=eval(expr).getDiagnostics();return d.pendingLoads===0&&ids.every(id=>d.representationGroups.some(g=>g.assetId===id&&["overview","detail"].includes(g.representation)))}',
                                   arg=[adapter,ids],timeout=180000)
            # Startup scene restoration can replace the first camera while CAD assets load.
            page.evaluate('([expr,p,t])=>{const a=eval(expr),v=a.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov:50,near:.05,far:300});a.applyCameraView(v)}',
                          [adapter,dict(zip('xyz',p)),dict(zip('xyz',t))])
            page.wait_for_timeout(700)
            view=page.evaluate(adapter+'.getCameraView()')
            assert all(abs(view['position'][axis]-value)<.001 for axis,value in zip('xyz',p)), 'Camera changed during capture'
            d=page.evaluate(adapter+'.getDiagnostics()')
            assert not d['degraded']
            assert d['placementTransformAudit']['transformMismatchCount']==0
            assert not [w for w in d['warnings'] if w.get('assetId') in ids]
            png=page.screenshot(path=str(OUT/f'desktop-{name}.png'),timeout=20000)
            pixels=list(Image.open(BytesIO(png)).convert('RGB').getdata())
            assert sum(r>60 and r>g*1.15 and g>b*1.35 for r,g,b in pixels)>80
            result['captures'].append(name)
        for relative,digest in json.loads((OUT/'report.json').read_bytes())['assetHashes'].items():
            served=page.evaluate('async u=>{const r=await fetch(u);if(!r.ok)throw Error(r.status);return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await r.arrayBuffer())),v=>v.toString(16).padStart(2,"0")).join("")}', '/'+relative)
            assert served==digest,'Desktop is serving an old model'
            result['servedAssetHashes'][relative]=served
        final=page.evaluate(app+'.session.getState()')
        assert final['layout']==saved and not final['dirty'] and path.read_bytes()==raw
        result.update(status='passed',savedBytesUnchanged=True,
                      meshGroups=[g for g in d['representationGroups'] if g['assetId'] in ids],
                      transformMismatchCount=0)
        write(OUT/'desktop-check.json',result)
        print(json.dumps(dict(status='passed',captures=len(result['captures']))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true')
    desktop() if parser.parse_args().desktop else verify()
