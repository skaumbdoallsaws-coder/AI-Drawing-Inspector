"""Render the exact staged reception arrangement with InspectorPro's Three adapter."""
from functools import partial
import argparse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from threading import Thread

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'
from PIL import Image
from playwright.sync_api import sync_playwright
from tools.import_private_gym_living_room import OUT, ASSET
from tools.build_private_gym import write


def main():
    fixture=json.loads((OUT/'render-fixture.json').read_bytes())
    raw=(OUT/'candidate.json').read_bytes()
    candidate=json.loads(raw)
    assert all(p in candidate['placements'] for p in fixture['layout']['placements'])
    # This isolated reception view excludes the other rooms and their wall attachments.
    finish=fixture['layout']['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks']=[]
    finish['wallFaces']=[]
    html='''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
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
        def log_message(self,*args): pass
        def do_GET(self):
            if self.path in ('/','/fixture.json'):
                content=html.encode() if self.path=='/' else json.dumps(fixture).encode()
                self.send_response(200)
                self.send_header('Content-Type','text/html' if self.path=='/' else 'application/json')
                self.send_header('Content-Length',str(len(content)))
                self.end_headers();self.wfile.write(content)
            elif self.path.startswith(('/static/','/generated/')): super().do_GET()
            else: self.send_error(404)
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
                    page.wait_for_function('window.ready===true',timeout=60000)
                    page.wait_for_function('adapter.getDiagnostics().pendingLoads===0',timeout=60000)
                    for name,pos,target in [('seating',(7,3.3,8.5),(1.7,.7,6.9)),('reception',(10.6,8,12.5),(4.2,0,5.4))]:
                        page.evaluate('([position,target])=>{const v=adapter.getCameraView();Object.assign(v,{position,target,up:{x:0,y:1,z:0},fov:65,near:.05,far:250});adapter.applyCameraView(v)}',
                            [dict(zip('xyz',pos)),dict(zip('xyz',target))])
                        page.wait_for_timeout(400)
                        shown=page.screenshot(path=str(OUT/f'{width}-{name}.png'))
                        assert len(set(Image.open(BytesIO(shown)).convert('RGB').getdata()))>1000
                        d=page.evaluate('adapter.getDiagnostics()')
                        group=next(g for g in d['representationGroups'] if g['assetId']==ASSET)
                        assert group['representation'] in ('overview','detail')
                        assert d['placementTransformAudit']['transformMismatchCount']==0
                        assert not d['warnings'],d['warnings']
                        report['captures'].append(dict(width=width,height=height,name=name,sha256=hashlib.sha256(shown).hexdigest()))
                    page.evaluate('adapter.dispose()');page.close()
                assert not errors,errors
                report['status']='passed'
            finally: browser.close()
    except Exception as e:
        report.update(status='failed',error=str(e),pageErrors=errors)
        raise
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        write(OUT/'renderer-check.json',report)
    print(json.dumps(dict(status=report['status'],captures=len(report['captures']))))


def desktop():
    from tools.build_private_gym import STORE, LAYOUT
    from tools.replace_private_gym_reception_sofa import audit, NEW
    app='window._trainFacilityLayoutAuthoringApp'
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=path.read_bytes()
    saved=json.loads(raw)
    report=dict(status='running',captures=[])
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        deadline=time.monotonic()+120
        page=None
        while page is None and time.monotonic()<deadline:
            page=next((p for c in browser.contexts for p in c.pages if p.url.startswith('http://127.0.0.1:8480/')),None)
            if page is None:time.sleep(.5)
        assert page is not None,'Desktop page not opened'
        page.wait_for_function(app+'?.session?.getState().loaded',timeout=120000)
        state=page.evaluate(app+'.session.getState()')
        assert state['layout']==saved and not state['dirty']
        catalog={a['assetId']:a for a in page.evaluate(app+'.workspace.assetCatalog.map(a=>a.source)')}
        checks=audit(json.loads((OUT/'layout-before.json').read_bytes()),saved,catalog)
        page.evaluate(app+".workspace._setViewMode('3d')")
        page.evaluate(app+".workspace.threeAdapter.exitWalkthrough('reception-review')")
        page.wait_for_function('id=>'+app+'.workspace.threeAdapter.getDiagnostics().representationGroups.some(g=>g.assetId===id)',arg=ASSET,timeout=60000)
        page.wait_for_function(app+'.workspace.threeAdapter.getDiagnostics().pendingLoads===0',timeout=120000)
        page.wait_for_timeout(700)
        for name,pos,target in [('close-up',(4.5,1.6,7),(1,.55,7)),
                ('reception',(10.6,8,12.5),(4.2,0,5.4)),('seating',(7,3.3,8.5),(1.7,.7,6.9))]:
            page.evaluate('([position,target])=>{const a='+app+'.workspace.threeAdapter,v=a.getCameraView();Object.assign(v,{position,target,up:{x:0,y:1,z:0},fov:65,near:.05,far:250});a.applyCameraView(v)}',
                [dict(zip('xyz',pos)),dict(zip('xyz',target))])
            page.wait_for_function('id=>'+app+'.workspace.threeAdapter.getDiagnostics().representationGroups.some(g=>g.assetId===id&&["overview","detail"].includes(g.representation))',arg=ASSET,timeout=120000)
            page.wait_for_timeout(500)
            shown=page.screenshot(path=str(OUT/('desktop-'+name+'.png')),timeout=20000)
            assert len(set(Image.open(BytesIO(shown)).convert('RGB').getdata()))>1000
            report['captures'].append(dict(name=name,sha256=hashlib.sha256(shown).hexdigest()))
        diagnostic=page.evaluate(app+'.workspace.threeAdapter.getDiagnostics()')
        group=next(g for g in diagnostic['representationGroups'] if g['assetId']==ASSET)
        assert group['placementIds']==[NEW]
        assert group['assetDefinitionRevision']==catalog[ASSET]['assetDefinitionRevision']
        assert not diagnostic['warnings'],diagnostic['warnings']
        url=catalog[ASSET]['overview']['path']
        served=page.evaluate('async url=>{const r=await fetch(url);if(!r.ok)throw Error(r.status);const h=await crypto.subtle.digest("SHA-256",await r.arrayBuffer());return Array.from(new Uint8Array(h),v=>v.toString(16).padStart(2,"0")).join("")}',url)
        assert served==hashlib.sha256((ROOT/url.lstrip('/')).read_bytes()).hexdigest()
        final=page.evaluate(app+'.session.getState()')
        assert final['layout']==saved and not final['dirty'] and final['selection']==state['selection']
        assert path.read_bytes()==raw
        report.update(status='passed',group=group,servedArtifactSha256=served,checks=checks,savedBytesUnchanged=True,warnings=[])
        write(OUT/'desktop-check.json',report)
        print(json.dumps(dict(status='passed',captures=len(report['captures']),saved=True)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true')
    args=parser.parse_args()
    desktop() if args.desktop else main()
