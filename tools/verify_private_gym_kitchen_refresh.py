"""Render the exact kitchen/patio candidate and verify its saved desktop assets."""
from copy import deepcopy
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from io import BytesIO
from threading import Thread
import argparse
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image,ImageChops
from playwright.sync_api import sync_playwright
from tools.update_private_gym_kitchen_refresh import OUT,STORE,LAYOUT,COFFEE,GRILL,WALL,ART,PREFIX,sha,write

SHOTS=[('espresso',(23.7,1.6,-13.7),(23.6,1.2,-15.2),[PREFIX+'espresso']),
       ('kitchen',(28.5,2.6,-12.5),(24.3,1.1,-15.5),[PREFIX+'espresso']),
       ('artwork',(26,1.7,-15),(26,1.7,-11.1),[PREFIX+'espresso']),
       ('grill',(77,1.65,66.3),(78.8,.8,63.8),[PREFIX+'grill']),
       ('patio',(80,4.5,70),(77.5,.5,65.2),[PREFIX+'grill'])]


def camera(page,expr,p,t,width):
    page.evaluate('([expr,p,t,fov])=>{const a=eval(expr),v=a.getCameraView();Object.assign(v,{position:p,target:t,up:{x:0,y:1,z:0},fov,near:.05,far:300});a.applyCameraView(v)}',
        [expr,dict(zip('xyz',p)),dict(zip('xyz',t)),85 if width<600 else 55])


def frame_check(d,report):
    a=next(a for a in d['exteriorArtwork'] if a['artworkId']==ART)
    assert a['status']=='ready' and a['target']==dict(placementId=WALL,face='negative_z')
    f=a['imageFrame'];b=report['source']['alphaBounds']
    w,h=a['worldWidth']*f['width'],a['worldHeight']*f['height']
    assert abs(w/h-(b[2]-b[0])/(b[3]-b[1]))<1e-5
    assert a['worldPosition']['z']<-11.08 and abs(a['worldPosition']['x']-26)<1e-5
    assert h>2.5 and a['worldPosition']['y']-h/2>=.3
    return dict(width=w,height=h,worldPosition=a['worldPosition'])


def capture(page,expr,name,p,t,ids,width,report):
    camera(page,expr,p,t,width);deadline=time.monotonic()+180
    while True:
        d=page.evaluate(expr+'.getDiagnostics()')
        if d['pendingLoads']==0 and all(any(g['assetId']==aid and g['representation'] in ('overview','detail') for g in d['representationGroups']) for aid in ids) and any(a['artworkId']==ART and a['status']=='ready' for a in d['exteriorArtwork']):break
        assert time.monotonic()<deadline,('Assets did not resolve',d)
        v=page.evaluate(expr+'.getCameraView()')
        if any(abs(v['position'][axis]-value)>.001 for axis,value in zip('xyz',p)):camera(page,expr,p,t,width)
        page.wait_for_timeout(1000)
    camera(page,expr,p,t,width);page.wait_for_timeout(700)
    d=page.evaluate(expr+'.getDiagnostics()');assert not d['degraded']
    assert d['placementTransformAudit']['transformMismatchCount']==0
    assert not [w for w in d['warnings'] if w.get('assetId') in ids or w.get('artworkId')==ART]
    frame=frame_check(d,report)
    png=page.screenshot(path=str(OUT/(name+'.png')),timeout=20000)
    pixels=list(Image.open(BytesIO(png)).convert('RGB').getdata());assert len(set(pixels))>500,'Blank viewport'
    return dict(name=name,artworkFrame=frame,meshGroups=[g for g in d['representationGroups'] if g['assetId'] in ids],transformMismatchCount=0),png


def staged():
    fixture=json.loads((OUT/'render-fixture.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
    report=json.loads((OUT/'report.json').read_bytes())
    assert all(p==next(a for a in candidate['placements'] if a['placementId']==p['placementId']) for p in fixture['layout']['placements'])
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
                self.send_header('Content-Type','text/html' if self.path=='/' else 'application/json');self.end_headers();self.wfile.write(data)
            else:
                if self.path=='/'+report['source']['artifact']:self.path='/'+(OUT/'staged-project').relative_to(ROOT).as_posix()+self.path
                super().do_GET()
    server=ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    thread=Thread(target=server.serve_forever,daemon=True);thread.start()
    result=dict(status='running',candidateSha256=sha(OUT/'candidate.json'),captures=[]);errors=[]
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
            try:
                for width,height in [(1440,900),(390,700)]:
                    page=browser.new_page(viewport=dict(width=width,height=height),device_scale_factor=1)
                    page.on('pageerror',lambda e:errors.append(str(e)));page.on('requestfailed',lambda r:errors.append(r.url+': '+str(r.failure)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/');page.wait_for_function('window.ready===true',timeout=120000)
                    for name,p,t,ids in SHOTS:
                        record,png=capture(page,'adapter',f'{width}-{name}',p,t,ids,width,report)
                        if name=='artwork':
                            page.evaluate('async()=>{const l=structuredClone(fixture.layout);l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks=[];await adapter.setScene({layout:l,assetCatalog:fixture.catalog})}')
                            page.wait_for_timeout(700);camera(page,'adapter',p,t,width);page.wait_for_timeout(500)
                            hidden=page.screenshot()
                            diff=ImageChops.difference(Image.open(BytesIO(png)).convert('RGB'),Image.open(BytesIO(hidden)).convert('RGB'))
                            changed=sum(max(pixel)>25 for pixel in diff.getdata());assert changed>1500,'Artwork is not visibly rendered'
                            record['artworkVisiblePixels']=changed
                            page.evaluate('async()=>{await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog})}')
                        result['captures'].append(record)
                    assert not errors,errors
                    page.evaluate('adapter.dispose()');page.close()
                result['status']='passed'
            finally:browser.close()
    except Exception as error:
        result.update(status='failed',error=str(error),errors=errors);raise
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5);write(OUT/'browser-check.json',result)
    print(json.dumps(dict(status=result['status'],captures=len(result['captures']))),flush=True)


def desktop():
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');raw=path.read_bytes();saved=json.loads(raw)
    assert saved==json.loads((OUT/'saved.json').read_bytes());report=json.loads((OUT/'report.json').read_bytes())
    app='window._trainFacilityLayoutAuthoringApp';expr=app+'.workspace.threeAdapter'
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        page=next(p for c in browser.contexts for p in c.pages if p.url.startswith('http://127.0.0.1:8480/'))
        page.wait_for_function(app+'?.session?.getState().loaded===true',timeout=120000)
        state=page.evaluate(app+'.session.getState()');assert not state['dirty'] and state['layout']==saved
        page.evaluate(app+".workspace._setViewMode('3d')");page.evaluate(expr+".exitWalkthrough('kitchen-refresh-review')")
        result=dict(status='running',captures=[],servedHashes={})
        for name,p,t,ids in SHOTS:result['captures'].append(capture(page,expr,'desktop-'+name,p,t,ids,1440,report)[0])
        hashes={**report['assetHashes'],report['source']['artifact']:report['source']['sha256']}
        for relative,digest in hashes.items():
            served=page.evaluate('async u=>{const r=await fetch(u);if(!r.ok)throw Error(r.status);return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await r.arrayBuffer())),v=>v.toString(16).padStart(2,"0")).join("")}', '/'+relative)
            assert served==digest,'Desktop is serving an old asset';result['servedHashes'][relative]=served
        final=page.evaluate(app+'.session.getState()');assert not final['dirty'] and final['layout']==saved and path.read_bytes()==raw
        camera(page,expr,SHOTS[1][1],SHOTS[1][2],1440)
        result.update(status='passed',savedBytesUnchanged=True);write(OUT/'desktop-check.json',result)
        print(json.dumps(dict(status='passed',captures=len(result['captures']))),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--desktop',action='store_true')
    desktop() if parser.parse_args().desktop else staged()
