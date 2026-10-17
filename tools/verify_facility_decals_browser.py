"""Exercise the actual decal UI, session, API, and Three renderer in an isolated store."""
import argparse
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
import socket
import sys
from threading import Thread
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
import uvicorn

from tests.test_facility_layout_api import _client, _layout, _principal
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.plan_settings import default_plan_settings
from ai_inspector.facility_layout.errors import FacilityNotFoundError

HTML = '''<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><link rel="icon" href="data:,">
<title>InspectorPro - Isolated Decals Preview</title>
<link rel="stylesheet" href="/static/facility_layout_workspace.css">
<style>html,body{margin:0;width:100%;height:100%;font-family:Segoe UI,Arial,sans-serif}#workspace{width:100%;height:100%;min-width:0;min-height:0}</style>
<script type="importmap">{"imports":{"three":"/static/vendor/three/0.184.0/build/three.module.min.js"}}</script>
<script src="/static/facility_layout_avatar.js"></script>
<script src="/static/walkthrough_camera_settings.js"></script>
<script src="/static/facility_layout_ground.js"></script>
<script src="/static/facility_layout_walls.js"></script>
<script src="/static/facility_layout_lettering.js"></script>
<script src="/static/facility_layout_authoring_dialog.js"></script>
<script src="/static/facility_layout_component_materials.js"></script>
<script src="/static/facility_layout_interior_walls.js"></script>
<script src="/static/facility_layout_floor_surfaces.js"></script>
<script src="/static/facility_layout_replace_asset.js"></script>
<script src="/static/facility_layout_decals.js"></script>
<script src="/static/facility_layout_editor.js"></script>
<script src="/static/facility_layout_three_adapter.js"></script>
<script src="/static/facility_layout_transport.js"></script>
<script src="/static/facility_layout_session.js"></script>
<script src="/static/facility_layout_workspace.js"></script>
</head><body><div id="workspace"></div><script type="module">
import * as THREE from 'three';
import {OrbitControls} from '/static/vendor/three/0.184.0/examples/jsm/controls/OrbitControls.js';
window.transport=InspectorProFacilityTransport.createHttpTransport({siteId:'site-a',layoutId:'fl-api-cell'});
window.session=InspectorProFacilitySession.createSession({...transport});
session.load(await transport.reloadLayout());
window.adapter=InspectorProFacilityThree.createThreeAdapter({THREE,OrbitControls,pixelRatio:1,
    worldBounds:{minX:0,minZ:0,maxX:40,maxZ:30,floorY:0}});
window.workspace=InspectorProFacilityWorkspace.createWorkspace({root:document.getElementById('workspace'),
    session,assetCatalog:[],threeAdapter:adapter,layoutRuntime:InspectorProFacilityLayout});
await workspace.controller.ready();workspace.controller.fit();window.ready=true;
window.startRenderProbe=async()=>{
    const host=document.createElement('div');host.id='render-probe';host.style.cssText='position:fixed;inset:0;z-index:9999';document.body.append(host);
    window.probeAdapter=InspectorProFacilityThree.createThreeAdapter({THREE,OrbitControls,pixelRatio:1,
        worldBounds:{minX:0,minZ:0,maxX:40,maxZ:30,floorY:0}});
    probeAdapter.mount(host);await probeAdapter.setScene({layout:session.getState().layout,assetCatalog:[]});
};
</script></body></html>'''


def build_app(output):
    client, service, shell, policy = _client(output / "data")
    try:
        service.get_layout(_principal(), "site-a", "fl-api-cell")
    except FacilityNotFoundError:
        doc = _layout(shell, policy)
        doc.setdefault('extensions', {})['facilityPlan'] = default_plan_settings()
        doc = apply_facility_layout_operations(doc, [{"op":"set_perimeter_walls","wallSettings":{
            "boundarySource":"plan","heightMeters":4,"thicknessMeters":.2,"interiorColor":"#45484b",
            "openings":[{"edge":0,"startMeters":5,"endMeters":8}]}}])["document"]
        service.create_layout(_principal(), "site-a", doc)
    app = client.app
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/")
    def index():
        return HTMLResponse(HTML)
    return app


def verify(output, port):
    server = uvicorn.Server(uvicorn.Config(build_app(output),host="127.0.0.1",port=port,log_level="error"))
    thread=Thread(target=server.run,daemon=True);thread.start()
    deadline=time.monotonic()+30
    while not server.started and time.monotonic()<deadline:time.sleep(.05)
    if not server.started:raise RuntimeError("Fixture server did not start")
    report={"status":"running","viewports":[]}
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
            try:
                page=browser.new_page(viewport={"width":1440,"height":900})
                errors=[];report['pageErrors']=errors
                page.on('pageerror',lambda error:errors.append(str(error)))
                page.goto(f"http://127.0.0.1:{port}/");page.wait_for_function('window.ready === true')
                before=page.evaluate('session.getState().layout')
                page.locator('[data-command="decals"]').click()
                page.get_by_label('Wall face',exact=True).select_option('1')
                page.get_by_label('Decal image',exact=True).set_input_files(str(ROOT/'static/logo.png'))
                page.get_by_role('button',name='Apply',exact=True).wait_for()
                page.wait_for_function('!document.querySelector(".ip-flw-decal-dialog button[type=submit]").disabled')
                page.get_by_label('Decal name',exact=True).fill('Entrance logo')
                page.get_by_label('Max width (m)',exact=True).fill('12')
                page.get_by_label('Max height (m)',exact=True).fill('3.4')
                page.get_by_label('From wall start (m)',exact=True).fill('10')
                page.get_by_label('Bottom (m)',exact=True).fill('0.3')
                for width,height in [(1440,900),(390,844)]:
                    page.set_viewport_size({"width":width,"height":height});page.wait_for_timeout(200)
                    dialog=page.get_by_role('dialog',name='Wall decals');box=dialog.bounding_box()
                    assert box['x']>=0 and box['x']+box['width']<=width
                    assert box['y']>=0 and box['y']+box['height']<=height
                    assert page.evaluate('document.querySelector(".ip-flw-decal-dialog").scrollWidth <= document.querySelector(".ip-flw-decal-dialog").clientWidth')
                    page.screenshot(path=str(output/f'{width}-dialog.png'))
                    report['viewports'].append({"width":width,"height":height,"dialogFits":True})
                page.set_viewport_size({"width":1440,"height":900})
                page.get_by_label('Max width (m)',exact=True).fill('45')
                assert page.get_by_role('button',name='Apply',exact=True).is_disabled()
                page.get_by_label('Max width (m)',exact=True).fill('12')
                page.get_by_role('button',name='Apply',exact=True).click()
                page.get_by_role('dialog',name='Wall decals').wait_for(state='detached')
                state=page.evaluate('session.getState()');assert state['dirty'] and len(state['history'])==1
                assert state['layout']['extensions']['facilityPerimeterWalls']==before['extensions']['facilityPerimeterWalls']
                record=state['layout']['extensions']['facilityDecals']['artworks'][0]
                # The edit remains local until an explicit Save.
                assert 'facilityDecals' not in page.evaluate('(async()=> (await transport.reloadLayout()).layout.extensions)()')
                page.evaluate('session.undo()');assert not page.evaluate('session.getState().dirty')
                page.evaluate('session.redo()');assert page.evaluate('session.getState().dirty')
                page.evaluate('workspace._setViewMode("3d")')
                page.evaluate('''(()=>{const v=adapter.getCameraView();v.position={x:16,y:3,z:15};v.target={x:16,y:2,z:0};v.up={x:0,y:1,z:0};adapter.applyCameraView(v);})()''')
                page.wait_for_function('adapter.getDiagnostics().exteriorArtwork.filter(a=>a.status==="ready").length === 1',timeout=30000)
                page.wait_for_timeout(500)
                visible=page.screenshot(path=str(output/'1440-decal-3d.png'))
                page.evaluate('adapter.setLayerVisibility({walls:false})');page.wait_for_timeout(300)
                hidden=page.screenshot()
                diff=ImageChops.difference(Image.open(BytesIO(visible)).convert('RGB'),Image.open(BytesIO(hidden)).convert('RGB'))
                changed=sum(1 for p in diff.getdata() if max(p)>20)
                assert changed>500
                page.evaluate('adapter.setLayerVisibility({walls:true})')
                page.evaluate('startRenderProbe()')
                page.wait_for_function('probeAdapter.getDiagnostics().exteriorArtwork.some(a=>a.status==="ready")')
                render_checks = []
                for width,height in [(1440,900),(390,844)]:
                    page.set_viewport_size(dict(width=width,height=height));page.wait_for_timeout(250)
                    page.evaluate('''(()=>{const r=document.getElementById('render-probe').getBoundingClientRect();const v=probeAdapter.getCameraView();
                        v.position={x:16,y:3,z:Math.max(15,6*r.height/r.width)};v.target={x:16,y:2,z:0};probeAdapter.applyCameraView(v);})()''')
                    page.wait_for_timeout(350)
                    capture=page.screenshot(path=str(output/f'{width}-rendered.png'))
                    rect=page.evaluate('document.getElementById("render-probe").getBoundingClientRect().toJSON()')
                    rgb=Image.open(BytesIO(capture)).convert('RGB')
                    crop=rgb.crop((max(0,int(rect['x'])),int(rect['y'])+80,min(width,int(rect['x']+rect['width'])),min(height,int(rect['y']+rect['height']))))
                    blue=sum(1 for r,g,b in crop.getdata() if r<60 and 70<g<170 and b>160)
                    assert blue>100,f'Logo pixels missing at {width}px'
                    view=page.evaluate('probeAdapter.getCameraView()')
                    page.evaluate('probeAdapter.zoomBy(1.1)');page.wait_for_timeout(200)
                    assert page.evaluate('probeAdapter.getCameraView()') != view
                    render_checks.append(dict(width=width,logoPixels=blue,cameraInteractive=True,isolatedRenderer=True))
                report['renderChecks']=render_checks
                page.evaluate('probeAdapter.dispose();document.getElementById("render-probe").remove()')
                page.set_viewport_size(dict(width=1440,height=900))
                page.locator('[data-command="decals"]').click()
                page.get_by_label('Decal',exact=True).select_option(record['artworkId'])
                page.wait_for_function('!document.querySelector(".ip-flw-decal-dialog button[type=submit]").disabled')
                page.get_by_label('Decal name',exact=True).fill('Renamed logo')
                page.get_by_role('button',name='Apply',exact=True).click()
                page.get_by_role('dialog',name='Wall decals').wait_for(state='detached')
                assert len(page.evaluate('session.getState().history'))==2
                page.evaluate('session.save()')
                assert not page.evaluate('session.getState().dirty')
                page.reload();page.wait_for_function('window.ready === true')
                assert page.evaluate('session.getState().layout.extensions.facilityDecals.artworks[0].label')=='Renamed logo'
                page.locator('[data-command="decals"]').click()
                page.get_by_label('Decal',exact=True).select_option(record['artworkId'])
                page.get_by_role('button',name='Delete decal',exact=True).click()
                page.get_by_role('dialog',name='Wall decals').wait_for(state='detached')
                assert page.evaluate('session.getState().layout.extensions.facilityDecals.artworks.length')==0
                page.evaluate('session.undo()')
                assert page.evaluate('session.getState().layout.extensions.facilityDecals.artworks.length')==1
                page.locator('[data-command="decals"]').click()
                page.evaluate('session.setPerimeterWalls({...session.getState().layout.extensions.facilityPerimeterWalls.settings,heightMeters:5})')
                assert page.get_by_role('button',name='Apply',exact=True).is_disabled()
                assert 'layout changed' in page.get_by_role('alert').inner_text()
                page.get_by_role('button',name='Cancel',exact=True).click()
                unchanged=page.evaluate('JSON.stringify(session.getState().layout)')
                page.locator('[data-command="decals"]').click()
                page.get_by_label('Decal image',exact=True).set_input_files(dict(name='bad.png',mimeType='image/png',buffer=b'not a PNG'))
                page.wait_for_function('document.querySelector(".ip-flw-decal-status").textContent.includes("decoded")')
                assert page.get_by_role('button',name='Apply',exact=True).is_disabled()
                page.get_by_role('button',name='Cancel',exact=True).click()
                assert page.evaluate('JSON.stringify(session.getState().layout)')==unchanged
                report['lettering'] = verify_lettering(page, output)
                report['existingLayoutGeometry'] = verify_existing_layouts(page)
                assert not errors,errors
                report.update(status='passed',changedPixels=changed,imageImport=True,preview=True,invalidSizeRejected=True,
                    oneGesture=True,undoRedo=True,edit=True,explicitSaveReload=True,deleteUndo=True,staleRejected=True,pageErrors=errors)
            finally:
                if report['status'] != 'passed':
                    page.screenshot(path=str(output/'failure.png'))
                browser.close()
    except Exception as error:
        report.update(status='failed',error=str(error))
        raise
    finally:
        server.should_exit=True;thread.join(timeout=15)
        (output/'report.json').write_text(json.dumps(report,indent=2))


def verify_lettering(page, output):
    before = page.evaluate('session.getState().history.length')
    page.locator('[data-command="lettering"]').click()
    page.get_by_label('Wall face', exact=True).select_option('1')
    page.get_by_label('Decal name', exact=True).fill('Entrance lettering')
    page.get_by_label('Lettering text', exact=True).fill('BUILD WITH PURPOSE')
    page.get_by_label('Lettering reference', exact=True).fill('INSPECTORPRO')
    page.get_by_label('Max width (m)', exact=True).fill('12')
    page.get_by_label('Max height (m)', exact=True).fill('3.4')
    page.get_by_label('From wall start (m)', exact=True).fill('25')
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size(dict(width=width, height=height))
        box = page.get_by_role('dialog', name='Wall lettering').bounding_box()
        assert box['x'] >= 0 and box['x']+box['width'] <= width
        page.screenshot(path=str(output/f'{width}-lettering-dialog.png'))
    page.set_viewport_size(dict(width=1440, height=900))
    page.get_by_role('button', name='Apply', exact=True).click()
    page.get_by_role('dialog', name='Wall lettering').wait_for(state='detached')
    state = page.evaluate('session.getState()')
    assert len(state['history']) == before+1
    art = state['layout']['extensions']['facilityDecals']['artworks'][-1]
    assert art['lettering']['text'] == 'BUILD WITH PURPOSE'
    page.evaluate('session.undo()')
    assert not page.evaluate('session.getState().layout.extensions.facilityDecals.artworks.some(a=>a.lettering)')
    page.evaluate('session.redo()')
    page.locator('[data-command="lettering"]').click()
    page.get_by_label('Decal', exact=True).select_option(art['artworkId'])
    assert page.get_by_label('Lettering text', exact=True).input_value() == 'BUILD WITH PURPOSE'
    page.get_by_label('Lettering text', exact=True).fill('CREATE WITH PURPOSE')
    page.get_by_role('button', name='Apply', exact=True).click()
    page.get_by_role('dialog', name='Wall lettering').wait_for(state='detached')
    page.evaluate('session.save()')
    page.reload();page.wait_for_function('window.ready === true')
    assert page.evaluate('session.getState().layout.extensions.facilityDecals.artworks.find(a=>a.lettering).lettering.text') == 'CREATE WITH PURPOSE'
    page.evaluate('workspace._setViewMode("3d")')
    page.evaluate('''(()=>{const v=adapter.getCameraView();v.position={x:31,y:3,z:15};v.target={x:31,y:2,z:0};adapter.applyCameraView(v);})()''')
    page.wait_for_function('adapter.getDiagnostics().exteriorArtwork.filter(a=>a.status==="ready").length === 2')
    page.screenshot(path=str(output/'lettering-3d.png'))
    return dict(editable=True, undoRedo=True, saveReload=True, textureReady=True)


def verify_existing_layouts(page):
    from ai_inspector.facility_layout.host import build_private_local_asset_catalog
    catalog = [item for item in build_private_local_asset_catalog(ROOT) if 'wall' in item.get('tags', [])]
    results = []
    for name in ('fl-private-gym-20261007','fl-independent-factory-20260928'):
        path = ROOT / '.runtime/facility-layout/layouts/local/site-local/layouts' / (name+'.json')
        if not path.is_file():
            results.append(dict(layoutId=name,status='not-available'));continue
        raw = path.read_bytes();doc = json.loads(raw)
        probe = page.evaluate('''({doc,catalog})=>{
            const targets=InspectorProFacilityDecals.targets(doc,catalog);
            if(!targets.length)throw new Error('No targets in '+doc.displayName);
            const s=targets[0], art=InspectorProFacilityDecals.makeRecord(s,{label:'Compatibility probe',
                width:(s.end-s.start)*.8,height:s.height*.8,offset:s.start+(s.end-s.start)*.1,bottom:s.height*.1,trim:true},
                {imagePath:'/api/facility-decal-images/site-local/'+ 'a'.repeat(64)+'.png',uv:[0,0,1,1]},'compatibility-probe');
            doc.extensions.facilityDecals={version:1,artworks:[art]};
            const surfaces=InspectorProFacilityWalls.fittedArtworkSurfaces(doc,id=>{
                const placement=doc.placements.find(p=>p.placementId===id);
                const entry=placement&&catalog.find(e=>e.assetId===placement.assetId&&e.assetDefinitionRevision===placement.assetDefinitionRevision);
                return entry?{placement,entry,bounds:entry.definition.geometry.aabb}:null;
            });
            const resolved=surfaces.find(s=>s.artwork.artworkId==='compatibility-probe');
            if(!resolved || resolved.width<=0 || resolved.height<=0)throw new Error('Decal surface missing');
            return {targetCount:targets.length,decals:doc.extensions.facilityDecals,width:resolved.width,height:resolved.height};
        }''',dict(doc=doc,catalog=catalog))
        candidate = apply_facility_layout_operations(doc,[dict(op='set_decals',decals=probe['decals'])])['document']
        assert candidate['placements'] == doc['placements']
        assert candidate['extensions'].get('facilityPerimeterWalls') == doc['extensions'].get('facilityPerimeterWalls')
        assert sha256(path.read_bytes()).digest() == sha256(raw).digest()
        results.append(dict(layoutId=name,status='passed',targetCount=probe['targetCount'],
            unchangedSavedFile=True,geometryOnly=True,width=probe['width'],height=probe['height']))
    return results


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);parser.add_argument('--serve',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args();args.output.mkdir(parents=True,exist_ok=True)
    port=args.port
    if not port:
        with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
    if args.serve:
        print(f'Isolated Decals preview: http://127.0.0.1:{port}/',flush=True)
        uvicorn.run(build_app(args.output),host='127.0.0.1',port=port,log_level='warning')
    else:verify(args.output,port)
