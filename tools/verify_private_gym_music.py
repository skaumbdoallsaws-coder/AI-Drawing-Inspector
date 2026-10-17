"""Inspect the staged music corner with the real renderer, then the saved desktop."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image
from playwright.sync_api import sync_playwright
from tools.import_private_gym_music import OUT
from tools.build_private_gym import write,STORE,LAYOUT

IDS=['asset-gym-music-'+k for k in ('steinway','electric-guitar','electric-guitar-gold','egg-chair')]
SHOTS=[
    ('music-wall',(2.65,1.65,-7),(2.65,1.45,-3.6)),
    ('piano',(4.3,1.5,-6),(2.65,.75,-3.7)),
    ('chairs',(2.7,1.65,-4.6),(2.7,.65,-7.2)),
    ('room',(11,2.9,-13),(3.3,1.05,-5.4)),
]


def camera(page,expr,p,t,width=1440):
    page.evaluate('([expr,p,t,fov])=>{const a=eval(expr),v=a.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov,near:.05,far:300});a.applyCameraView(v)}',
        [expr,dict(zip('xyz',p)),dict(zip('xyz',t)),85 if width<600 else 55])


def capture(page,expr,name,p,t,width=1440):
    camera(page,expr,p,t,width)
    deadline=time.monotonic()+180
    while True:
        d=page.evaluate(expr+'.getDiagnostics()')
        if d['pendingLoads']==0 and all(any(g['assetId']==aid and g['representation'] in ('overview','detail') for g in d['representationGroups']) for aid in IDS):break
        assert time.monotonic()<deadline,('Music models did not resolve',d)
        v=page.evaluate(expr+'.getCameraView()')
        if any(abs(v['position'][axis]-value)>.001 for axis,value in zip('xyz',p)):
            camera(page,expr,p,t,width)
        page.wait_for_timeout(1000)
    camera(page,expr,p,t,width)
    page.wait_for_timeout(700)
    v=page.evaluate(expr+'.getCameraView()')
    assert all(abs(v['position'][axis]-value)<.001 for axis,value in zip('xyz',p))
    d=page.evaluate(expr+'.getDiagnostics()')
    assert not d['degraded']
    assert d['placementTransformAudit']['transformMismatchCount']==0
    assert not [w for w in d['warnings'] if w.get('assetId') in IDS]
    png=page.screenshot(path=str(OUT/(name+'.png')),timeout=20000)
    pixels=list(Image.open(BytesIO(png)).convert('RGB').getdata())
    gold=sum(r>60 and r>g*1.15 and g>b*1.35 for r,g,b in pixels)
    assert gold>80,(name,gold)
    assert len(set(pixels))>100,'Blank viewport'
    return dict(name=name,goldPixels=gold,meshGroups=[g for g in d['representationGroups'] if g['assetId'] in IDS],transformMismatchCount=0)


def verify():
    raw=(OUT/'candidate.json').read_bytes();candidate=json.loads(raw)
    fixture=json.loads((OUT/'render-fixture.json').read_bytes())
    for placement in fixture['layout']['placements']:
        assert placement==next(p for p in candidate['placements'] if p['placementId']==placement['placementId'])
    for relative,digest in json.loads((OUT/'report.json').read_bytes())['assetHashes'].items():
        assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest
    html='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
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
      worldBounds:{minX:0,minZ:-18,maxX:22,maxZ:-3,floorY:0},
      assetResolver:r=>r.stage==='overview'?fixture.artifacts[r.assetId]:null});
    adapter.mount(document.getElementById('scene'));
    await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog});window.ready=true;
    </script></body></html>'''
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path in ('/','/fixture.json'):
                data=html.encode() if self.path=='/' else json.dumps(fixture).encode()
                self.send_response(200);self.send_header('Content-Type','text/html' if self.path=='/' else 'application/json')
                self.send_header('Content-Length',str(len(data)));self.end_headers();self.wfile.write(data)
            else:super().do_GET()
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    report=dict(status='running',candidateSha256=hashlib.sha256(raw).hexdigest(),captures=[])
    errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
            try:
                for width,height in [(1440,900),(390,700)]:
                    page=browser.new_page(viewport=dict(width=width,height=height),device_scale_factor=1)
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('requestfailed',lambda r:errors.append(r.url+': '+str(r.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true',timeout=120000)
                    for name,p,t in SHOTS:
                        if width<600 and name=='chairs':p=(2.7,1.65,-3.6)
                        report['captures'].append(capture(page,'adapter',f'{width}-{name}',p,t,width))
                    assert not errors,errors
                    page.evaluate('adapter.dispose()');page.close()
                report['status']='passed'
            finally:browser.close()
    except Exception as error:
        report.update(status='failed',error=str(error),pageErrors=errors);raise
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);write(OUT/'browser-check.json',report)
    print(json.dumps(dict(status=report['status'],captures=len(report['captures']))),flush=True)


def desktop(check_only=False):
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=path.read_bytes();saved=json.loads(raw)
    app='window._trainFacilityLayoutAuthoringApp';adapter=app+'.workspace.threeAdapter'
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        page=next(p for c in browser.contexts for p in c.pages if p.url.startswith('http://127.0.0.1:8480/'))
        page.wait_for_function(app+'?.session?.getState().loaded===true',timeout=120000)
        state=page.evaluate(app+'.session.getState()')
        assert not state['dirty'] and state['layout']==saved,'Desktop has unsaved or stale layout data'
        if check_only:
            print(json.dumps(dict(dirty=state['dirty'],layoutId=state['layout']['layoutId'],placements=len(state['layout']['placements']))),flush=True)
            return
        assert saved==json.loads((OUT/'saved.json').read_bytes())
        page.evaluate(app+".workspace._setViewMode('3d')")
        page.evaluate(adapter+".exitWalkthrough('music-review')")
        result=dict(status='running',captures=[],servedAssetHashes={})
        for name,p,t in SHOTS:result['captures'].append(capture(page,adapter,'desktop-'+name,p,t))
        for relative,digest in json.loads((OUT/'report.json').read_bytes())['assetHashes'].items():
            served=page.evaluate('async u=>{const r=await fetch(u);if(!r.ok)throw Error(r.status);return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await r.arrayBuffer())),v=>v.toString(16).padStart(2,"0")).join("")}', '/'+relative)
            assert served==digest,'Desktop is serving an old model'
            result['servedAssetHashes'][relative]=served
        final=page.evaluate(app+'.session.getState()')
        assert final['layout']==saved and not final['dirty'] and path.read_bytes()==raw
        camera(page,adapter,SHOTS[0][1],SHOTS[0][2])
        result.update(status='passed',savedBytesUnchanged=True)
        write(OUT/'desktop-check.json',result)
        print(json.dumps(dict(status='passed',captures=len(result['captures']))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true');parser.add_argument('--check-dirty',action='store_true')
    args=parser.parse_args()
    desktop(args.check_dirty) if args.desktop or args.check_dirty else verify()
