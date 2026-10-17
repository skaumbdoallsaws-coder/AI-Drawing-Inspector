"""Verify kitchen placement and transparent soccer graphics in Three.js and desktop."""
import argparse
from copy import deepcopy
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
import json
import os
from pathlib import Path
import sys
from threading import Thread

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY']='1'
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
from tools.update_private_gym_kitchen_soccer import OUT, SPECS, KITCHEN, audit, sha, STORE, LAYOUT, write

SHOTS=[('kitchen',(19,10,-8),(25,0,-14.5)),
       ('soccer-speed-discipline',(14.55,3.4,54),(14.55,3.1,34.275)),
       ('soccer-train-champion',(11,4,48),(.275,4.1,48)),
       ('soccer-play-belong',(30,4,48),(41.725,4.1,48))]


def camera(page,adapter,p,t,mobile=False):
    page.evaluate('([expr,p,t,fov])=>{const a=eval(expr),v=a.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov,near:.05,far:300});a.applyCameraView(v)}',
        [adapter,dict(zip('xyz',p)),dict(zip('xyz',t)),85 if mobile else 60])
    page.wait_for_timeout(700)


def ready(page,adapter):
    page.wait_for_function('([expr,ids])=>{const d=eval(expr).getDiagnostics();return d.pendingLoads===0&&ids.every(id=>d.exteriorArtwork.some(a=>a.artworkId===id&&a.status==="ready"))}',
        arg=[adapter,[s['id'] for s in SPECS]],timeout=120000)
    page.wait_for_timeout(700)


def check_diagnostics(d,sources):
    assert not d['warnings'],d['warnings']
    assert d['placementTransformAudit']['transformMismatchCount']==0
    result=[]
    for source,spec in zip(sources,SPECS):
        art=next(a for a in d['exteriorArtwork'] if a['artworkId']==spec['id'])
        assert art['status']=='ready' and art['target']==dict(placementId=spec['wall'],face=spec['face'])
        frame=art['imageFrame'];box=source['alphaBounds']
        width=art['worldWidth']*frame['width'];height=art['worldHeight']*frame['height']
        assert abs(width/height-(box[2]-box[0])/(box[3]-box[1]))<1e-5
        assert all(0<=frame[k]<=1 for k in ['x','y','width','height'])
        pos=art['worldPosition']
        if 'goal' in spec:
            assert abs(pos['z']-48)<1e-6
            assert pos['y']-height/2>=2.23-1e-5
        else:
            assert abs(pos['x']-14.55)<1e-5 and width>18
        result.append(dict(artworkId=spec['id'],visibleWidth=width,visibleHeight=height,worldPosition=pos))
    return result


def staged():
    fixture=json.loads((OUT/'render-fixture.json').read_bytes())
    candidate=json.loads((OUT/'candidate.json').read_bytes())
    for p in fixture['layout']['placements']:
        assert p==next(x for x in candidate['placements'] if x['placementId']==p['placementId'])
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
        def log_message(self,*args):pass
        def do_GET(self):
            if self.path in ('/','/fixture.json'):
                data=html.encode() if self.path=='/' else json.dumps(fixture).encode()
                self.send_response(200);self.send_header('Content-Length',str(len(data)))
                self.send_header('Content-Type','text/html' if self.path=='/' else 'application/json')
                self.end_headers();self.wfile.write(data)
            elif self.path.startswith(('/static/','/generated/')):
                if self.path in [s['imagePath'] for s in fixture['layout']['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks']]:
                    self.path='/'+(OUT/'staged-project').relative_to(ROOT).as_posix()+self.path
                super().do_GET()
            else:self.send_error(404)
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    report=dict(status='running',candidateSha256=sha(OUT/'candidate.json'),captures=[])
    errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
            try:
                for width,height in [(1440,900),(390,700)]:
                    page=browser.new_page(viewport=dict(width=width,height=height))
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.on('requestfailed',lambda r:errors.append(r.url+': '+str(r.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true');ready(page,'adapter')
                    frames=check_diagnostics(page.evaluate('adapter.getDiagnostics()'),fixture['sources'])
                    for name,p,t in SHOTS:
                        if width==390 and name=='soccer-speed-discipline':p=(14.55,3.4,59.5)
                        camera(page,'adapter',p,t,width==390)
                        shown=page.screenshot(path=str(OUT/f'{width}-{name}.png'),timeout=20000)
                        assert len(set(Image.open(BytesIO(shown)).convert('RGB').getdata()))>1000
                        capture=dict(name=f'{width}-{name}')
                        if name in fixture['ids'] or name=='room':
                            hidden_ids=fixture['ids'] if name=='room' else [name]
                            page.evaluate('async ids=>{const l=structuredClone(fixture.layout);l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks=l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks.filter(a=>!ids.includes(a.artworkId));await adapter.setScene({layout:l,assetCatalog:fixture.catalog})}',hidden_ids)
                            page.wait_for_function('adapter.getDiagnostics().pendingLoads===0');page.wait_for_timeout(700)
                            hidden=page.screenshot(timeout=20000)
                            diff=ImageChops.difference(Image.open(BytesIO(shown)).convert('RGB'),Image.open(BytesIO(hidden)).convert('RGB'))
                            changed=sum(1 for pixel in diff.getdata() if max(pixel)>25)
                            assert changed>500, (name,'Artwork is not visibly rendered',changed)
                            capture['changedPixels']=changed
                            page.evaluate('async()=>{await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog})}')
                            ready(page,'adapter')
                        report['captures'].append(capture)
                    if width==1440:
                        baseline=page.evaluate('adapter.getDiagnostics().exteriorArtwork')
                        page.evaluate('async ids=>{const l=structuredClone(fixture.layout);l.placements.filter(p=>ids.includes(p.placementId)).forEach(p=>{p.transform.scale*=1.1;p.transform.position.x+=1});await adapter.setScene({layout:l,assetCatalog:fixture.catalog})}',[s['wall'] for s in SPECS])
                        ready(page,'adapter')
                        resized=page.evaluate('adapter.getDiagnostics().exteriorArtwork')
                        for a,b in zip(baseline,resized):
                            assert a['artworkId']==b['artworkId']
                            assert abs(b['worldWidth']/a['worldWidth']-1.1)<1e-6
                            assert abs(b['worldHeight']/a['worldHeight']-1.1)<1e-6
                        report['wallAttachmentResizeVerified']=True
                    page.evaluate('adapter.dispose()');page.close()
                assert not errors,errors
                report.update(status='passed',artworkFrames=frames)
            finally:browser.close()
    except Exception as exc:
        report.update(status='failed',error=str(exc),errors=errors);raise
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
        write(OUT/'renderer-check.json',report)
    print(json.dumps(dict(status=report['status'],captures=len(report['captures']))))


def desktop():
    app='window._trainFacilityLayoutAuthoringApp'
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=target.read_bytes();saved=json.loads(raw)
    report=json.loads((OUT/'report.json').read_bytes())
    result=dict(status='running',captures=[])
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        page=next(p for c in browser.contexts for p in c.pages if p.url.startswith('http://127.0.0.1:8480/'))
        page.wait_for_function(app+'?.session?.getState().loaded',timeout=120000)
        state=page.evaluate(app+'.session.getState()')
        assert not state['dirty'] and state['layout']==saved, 'Desktop must show the exact saved gym'
        catalog={a['assetId']:a for a in page.evaluate(app+'.workspace.assetCatalog.map(a=>a.source)')}
        result['checks']=audit(json.loads((OUT/'before.json').read_bytes()),saved,catalog,report['records'])
        page.evaluate(app+".workspace._setViewMode('3d')")
        adapter=app+'.workspace.threeAdapter'
        page.evaluate(adapter+".exitWalkthrough('kitchen-soccer-review')")
        ready(page,adapter)
        result['artworkFrames']=check_diagnostics(page.evaluate(adapter+'.getDiagnostics()'),report['sources'])
        for name,p,t in SHOTS:
            camera(page,adapter,p,t)
            page.screenshot(path=str(OUT/f'desktop-{name}.png'),timeout=20000)
            result['captures'].append(name)
        for source in report['sources']:
            served=page.evaluate('async u=>{const r=await fetch(u);if(!r.ok)throw Error(r.status);return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await r.arrayBuffer())),v=>v.toString(16).padStart(2,"0")).join("")}', '/'+source['artifact'])
            assert served==source['sha256']
        camera(page,adapter,SHOTS[0][1],SHOTS[0][2])
        final=page.evaluate(app+'.session.getState()')
        assert not final['dirty'] and final['layout']==saved and target.read_bytes()==raw
        result.update(status='passed',savedBytesUnchanged=True,servedArtworkHashesVerified=True)
        write(OUT/'desktop-check.json',result)
        print(json.dumps(dict(status='passed',captures=len(result['captures']))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--desktop',action='store_true')
    desktop() if parser.parse_args().desktop else staged()
