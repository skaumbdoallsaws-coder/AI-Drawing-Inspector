"""Exercise manual facility authoring tools with an isolated persisted layout."""
import argparse
from copy import deepcopy
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
from PIL import Image
from playwright.sync_api import sync_playwright
import uvicorn
from tools.verify_facility_decals_browser import HTML
from tests.test_facility_layout_api import _client, _layout, _placement_operation, _resolved_asset, _principal
from ai_inspector.facility_layout.plan_settings import default_plan_settings
from ai_inspector.facility_layout.errors import FacilityNotFoundError


def build_app(output):
    client, service, shell, policy = _client(output/'data')
    first = _placement_operation()['placement']
    first['transform']['position'].update(x=10, y=0, z=10)
    second = deepcopy(first)
    second['placementId'] = 'pl-other'
    second['transform']['position']['x'] = 15
    entry = _resolved_asset(first['assetId'], first['assetDefinitionRevision'])
    catalog = [dict(assetId=first['assetId'], assetDefinitionRevision=first['assetDefinitionRevision'], displayName='Test machine', **entry)]
    catalog.append(dict(assetId='asset-replacement',assetDefinitionRevision='b'*64,displayName='Replacement machine',**_resolved_asset('asset-replacement','b'*64)))
    try:
        service.get_layout(_principal(), 'site-a', 'fl-api-cell')
    except FacilityNotFoundError:
        doc = _layout(shell, policy)
        doc.setdefault('extensions', {})['facilityPlan'] = default_plan_settings()
        doc['placements'] = [first, second]
        service.create_layout(_principal(), 'site-a', doc)
    app = client.app
    app.mount('/static', StaticFiles(directory=ROOT/'static'), name='static')
    markup = HTML.replace('Isolated Decals Preview', 'Isolated Authoring Preview')
    markup = markup.replace('window.transport=', 'window.catalog='+json.dumps(catalog)+';window.transport=')
    markup = markup.replace('assetCatalog:[]', 'assetCatalog:window.catalog')
    markup = markup.replace('worldBounds:{minX:0', '''assetResolver:request=>{
        if(request.stage==='manifest')return window.catalog[0];
        if(request.stage!=='overview')return null;
        const object=new THREE.Group();
        for(const [name,color,y,w,h] of [['Frame',0x17191c,.7,1.4,1.4],['Seat',0x35393e,1.55,1.8,.3]]){
            const material=new THREE.MeshStandardMaterial({color,roughness:.65,metalness:.15});
            material.userData.facilityPreserveMaterial=true;
            const mesh=new THREE.Mesh(new THREE.BoxGeometry(w,h,1),material);mesh.name=name;mesh.position.y=y;object.add(mesh);
        }
        return {object};
    },worldBounds:{minX:0''')
    @app.get('/')
    def index(): return HTMLResponse(markup)
    return app


def dialog_viewports(page, output, title, filename):
    for width, height in [(1440, 900), (390, 844)]:
        page.set_viewport_size(dict(width=width, height=height))
        dialog = page.get_by_role('dialog', name=title, exact=True)
        box = dialog.bounding_box()
        assert box['x'] >= 0 and box['x']+box['width'] <= width
        assert box['y'] >= 0 and box['y']+box['height'] <= height
        assert dialog.evaluate('n=>n.scrollWidth<=n.clientWidth')
        assert dialog.evaluate('n=>n.querySelector(".ip-flw-authoring-scroll").getBoundingClientRect().bottom<=n.querySelector("footer").getBoundingClientRect().top')
        for item in [dialog.get_by_role('heading'), dialog.get_by_role('button', name='Apply', exact=True)]:
            bounds=item.bounding_box()
            assert bounds['y']>=0 and bounds['y']+bounds['height']<=height
        page.screenshot(path=str(output/f'{width}-{filename}.png'))
    page.set_viewport_size(dict(width=1440, height=900))


def materials(page, output):
    page.evaluate('workspace._setViewMode("3d")')
    page.evaluate('session.select(session.getState().layout.placements[0].placementId)')
    page.locator('[data-command="component-materials"]').click()
    page.get_by_label('Component', exact=True).wait_for()
    page.get_by_label('Component', exact=True).select_option('m1-s0')
    page.get_by_label('Component color', exact=True).fill('#c99b39')
    dialog=page.get_by_role('dialog',name='Component Materials')
    dialog.get_by_label('Roughness',exact=True).evaluate("n=>{n.value=.35;n.dispatchEvent(new Event('input',{bubbles:true}));}")
    dialog.get_by_label('Metalness',exact=True).evaluate("n=>{n.value=.7;n.dispatchEvent(new Event('input',{bubbles:true}));}")
    dialog_viewports(page, output, 'Component Materials', 'materials-dialog')
    page.get_by_role('button',name='Apply',exact=True).click()
    page.get_by_role('dialog',name='Component Materials').wait_for(state='detached')
    state=page.evaluate('session.getState()')
    assert len(state['history'])==1
    assert 'componentMaterials' not in state['layout']['placements'][1]
    page.evaluate('session.undo()')
    assert not page.evaluate('session.getState().layout.placements[0].componentMaterials')
    page.evaluate('session.redo()');page.evaluate('session.save()')
    page.reload();page.wait_for_function('window.ready === true')
    assert page.evaluate('session.getState().layout.placements[0].componentMaterials.overrides[0].color')=='#c99b39'
    page.evaluate('workspace._setViewMode("3d")')
    page.evaluate('''(()=>{const v=adapter.getCameraView();v.position={x:12.5,y:4,z:20};v.target={x:12.5,y:1,z:10};adapter.applyCameraView(v);})()''')
    page.wait_for_timeout(500)
    capture=page.screenshot(path=str(output/'materials-3d.png'))
    rgb=Image.open(BytesIO(capture)).convert('RGB')
    gold=sum(1 for r,g,b in rgb.getdata() if r>130 and 65<g<200 and b<110 and r>g*1.1)
    assert gold>100, f'Material pixels missing: {gold}'
    page.evaluate('session.select(session.getState().layout.placements[0].placementId)')
    page.locator('[data-command="component-materials"]').click()
    page.get_by_label('Component',exact=True).select_option('m1-s0')
    page.get_by_role('button',name='Restore this component',exact=True).click()
    page.get_by_role('button',name='Apply',exact=True).click()
    page.get_by_role('dialog',name='Component Materials').wait_for(state='detached')
    assert not page.evaluate('session.getState().layout.placements[0].componentMaterials')
    page.evaluate('session.undo()')
    return dict(undoRedo=True,saveReload=True,reset=True,otherOccurrenceUnchanged=True,goldPixels=gold)


def interiors(page, output):
    count=page.evaluate('session.getState().historyCursor')
    before=page.evaluate('JSON.stringify(session.getState().layout.placements)')
    page.locator('[data-command="interior-walls"]').click()
    page.get_by_label('Wall name',exact=True).fill('Office partition')
    page.get_by_label('Start X (m)',exact=True).fill('20')
    page.get_by_label('End X (m)',exact=True).fill('20')
    page.get_by_label('End Z (m)',exact=True).fill('25')
    page.get_by_role('button',name='Add opening',exact=True).click()
    page.get_by_label('Door start (m)',exact=True).fill('5')
    page.get_by_label('Door end (m)',exact=True).fill('8')
    dialog_viewports(page, output, 'Interior Walls', 'interior-wall-dialog')
    page.get_by_role('button',name='Apply',exact=True).click()
    page.get_by_role('dialog',name='Interior Walls').wait_for(state='detached')
    state=page.evaluate('session.getState()');assert state['historyCursor']==count+1
    wall=state['layout']['extensions']['facilityInteriorWalls']['walls'][0]
    assert len(wall['panels'])==2
    assert page.evaluate('JSON.stringify(session.getState().layout.placements)')==before
    assert page.evaluate('InspectorProFacilityWalls.volumes(session.getState().layout).length')==2
    page.evaluate('session.undo()');assert not page.evaluate('session.getState().layout.extensions.facilityInteriorWalls')
    page.evaluate('session.redo()');page.evaluate('session.save()')
    page.reload();page.wait_for_function('window.ready === true')
    page.evaluate('workspace._setViewMode("3d")')
    page.evaluate('''(()=>{const v=adapter.getCameraView();v.position={x:31,y:8,z:18};v.target={x:20,y:1,z:15};adapter.applyCameraView(v);})()''')
    page.wait_for_timeout(500);page.screenshot(path=str(output/'interior-wall-3d.png'))
    page.locator('[data-command="decals"]').click()
    assert 'Office partition' in page.get_by_label('Wall face',exact=True).inner_text()
    page.get_by_role('button',name='Cancel',exact=True).click()
    page.locator('[data-command="interior-walls"]').click()
    page.get_by_label('Wall',exact=True).select_option(wall['wallId'])
    page.get_by_role('button',name='Delete wall',exact=True).click()
    page.get_by_role('dialog',name='Interior Walls').wait_for(state='detached')
    assert page.evaluate('session.getState().layout.extensions.facilityInteriorWalls.walls.length')==0
    page.evaluate('session.undo()')
    return dict(doorClear=True,undoRedo=True,saveReload=True,decalsAvailable=True,deleteUndo=True,placementsUnchanged=True)


def floors(page, output):
    count=page.evaluate('session.getState().historyCursor')
    before=page.evaluate('JSON.stringify(session.getState().layout.placements)')
    page.locator('[data-command="floor-surfaces"]').click()
    page.get_by_label('Surface name',exact=True).fill('Training turf')
    page.get_by_label('Floor material',exact=True).select_option('turf')
    page.get_by_label('Origin X (m)',exact=True).fill('21')
    page.get_by_label('Origin Z (m)',exact=True).fill('6')
    page.get_by_label('Surface depth (m)',exact=True).fill('18')
    dialog_viewports(page, output, 'Floor Surfaces', 'floor-surface-dialog')
    page.get_by_role('button',name='Apply',exact=True).click()
    page.get_by_role('dialog',name='Floor Surfaces').wait_for(state='detached')
    state=page.evaluate('session.getState()');assert state['historyCursor']==count+1
    surface=state['layout']['extensions']['facilityFloorSurfaces']['surfaces'][0]
    assert page.evaluate('JSON.stringify(session.getState().layout.placements)')==before
    assert 'facilityGround' not in state['layout']['extensions']
    page.evaluate('session.undo()');assert not page.evaluate('session.getState().layout.extensions.facilityFloorSurfaces')
    page.evaluate('session.redo()');page.evaluate('session.save()')
    page.reload();page.wait_for_function('window.ready === true')
    page.evaluate('workspace._setViewMode("3d")')
    page.evaluate('''(()=>{const v=adapter.getCameraView();v.position={x:35,y:17,z:27};v.target={x:24,y:0,z:15};adapter.applyCameraView(v);})()''')
    page.wait_for_timeout(400)
    capture=page.screenshot(path=str(output/'floor-surfaces-3d.png'))
    rgb=Image.open(BytesIO(capture)).convert('RGB')
    green=sum(1 for r,g,b in rgb.getdata() if g>r*1.25 and g>b*1.2 and g>40)
    assert green>1000,f'Turf pixels missing: {green}'
    page.locator('[data-command="floor-surfaces"]').click()
    page.get_by_label('Surface',exact=True).select_option(surface['surfaceId'])
    page.get_by_role('button',name='Delete floor surface',exact=True).click()
    page.get_by_role('dialog',name='Floor Surfaces').wait_for(state='detached')
    assert page.evaluate('session.getState().layout.extensions.facilityFloorSurfaces.surfaces.length')==0
    page.evaluate('session.undo()')
    return dict(undoRedo=True,saveReload=True,deleteUndo=True,groundUnchanged=True,placementsUnchanged=True,greenPixels=green)


def replace(page, output):
    page.evaluate('session.select(session.getState().layout.placements[0].placementId)')
    before=page.evaluate('session.getState()')
    page.locator('[data-command="replace-asset"]').click()
    page.get_by_role('button',name='Check placement',exact=True).click()
    page.wait_for_function('!document.querySelector(".ip-flw-authoring-dialog button[type=submit]").disabled')
    assert page.evaluate('session.getState().draftRevision')==before['draftRevision']
    dialog_viewports(page, output, 'Replace Asset', 'replacement-dialog')
    page.get_by_role('button',name='Apply',exact=True).click()
    page.get_by_role('dialog',name='Replace Asset').wait_for(state='detached')
    state=page.evaluate('session.getState()')
    assert state['historyCursor']==before['historyCursor']+1
    assert state['layout']['placements'][0]['assetId']=='asset-replacement'
    assert state['layout']['placements'][0]['transform']==before['layout']['placements'][0]['transform']
    assert state['layout']['placements'][0]['placementId']==before['layout']['placements'][0]['placementId']
    assert state['layout']['placements'][1]==before['layout']['placements'][1]
    assert 'componentMaterials' not in state['layout']['placements'][0]
    page.evaluate('session.undo()');assert page.evaluate('session.getState().draftRevision')==before['draftRevision']
    page.evaluate('session.redo()');page.evaluate('session.save()')
    page.reload();page.wait_for_function('window.ready === true')
    assert page.evaluate('session.getState().layout.placements[0].assetId')=='asset-replacement'
    return dict(readOnlyCheck=True,identityPreserved=True,transformPreserved=True,otherOccurrenceUnchanged=True,undoRedo=True,saveReload=True)


def dialog_safety(page):
    before = page.evaluate('session.getState().draftRevision')
    page.locator('[data-command="floor-surfaces"]').click()
    page.get_by_label('Surface name', exact=True).fill('Cancelled draft')
    page.get_by_role('button', name='Cancel', exact=True).click()
    assert page.evaluate('session.getState().draftRevision') == before
    page.evaluate('session.select(session.getState().layout.placements[0].placementId)')
    page.locator('[data-command="interior-walls"]').click()
    page.evaluate('session.select(session.getState().layout.placements[1].placementId)')
    assert page.get_by_role('button', name='Apply', exact=True).is_disabled()
    assert 'changed' in page.get_by_role('dialog').get_by_role('status').inner_text()
    page.get_by_role('button', name='Cancel', exact=True).click()
    assert page.evaluate('session.getState().draftRevision') == before
    return dict(cancelUnchanged=True, staleSelectionRejected=True)


def render_viewports(page, output):
    page.evaluate('startRenderProbe()')
    results = []
    try:
        for width, height in [(1440, 900), (390, 844)]:
            page.set_viewport_size(dict(width=width, height=height))
            page.wait_for_timeout(250)
            page.evaluate('''(()=>{const v=probeAdapter.getCameraView();
                const aspect=innerHeight/innerWidth,factor=Math.max(1,aspect);
                v.position={x:24+11*factor,y:20*factor,z:15+12*factor};
                v.target={x:24,y:0,z:15};probeAdapter.applyCameraView(v);})()''')
            page.wait_for_timeout(350)
            capture=page.screenshot(path=str(output/f'{width}-authoring-rendered.png'))
            rgb=Image.open(BytesIO(capture)).convert('RGB')
            green=sum(1 for r,g,b in rgb.getdata() if g>r*1.25 and g>b*1.2 and g>40)
            assert green>1000,f'Floor surface pixels missing at {width}px: {green}'
            view=page.evaluate('probeAdapter.getCameraView()')
            page.evaluate('probeAdapter.zoomBy(1.1)')
            page.wait_for_timeout(200)
            assert page.evaluate('probeAdapter.getCameraView()') != view
            results.append(dict(width=width,greenPixels=green,cameraInteractive=True,isolatedRenderer=True))
    finally:
        page.evaluate('probeAdapter.dispose();document.getElementById("render-probe").remove()')
        page.set_viewport_size(dict(width=1440,height=900))
    return results


def verify(output, port):
    server=uvicorn.Server(uvicorn.Config(build_app(output),host='127.0.0.1',port=port,log_level='error'))
    thread=Thread(target=server.run,daemon=True);thread.start()
    deadline=time.monotonic()+30
    while not server.started and time.monotonic()<deadline:time.sleep(.05)
    if not server.started:raise RuntimeError('Server did not start')
    report=dict(status='running',pageErrors=[])
    try:
        with sync_playwright() as pw:
            browser=pw.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
            page=browser.new_page(viewport=dict(width=1440,height=900))
            page.on('pageerror',lambda e:report['pageErrors'].append(str(e)))
            try:
                page.goto(f'http://127.0.0.1:{port}/');page.wait_for_function('window.ready === true')
                report['materials']=materials(page,output)
                report['interiors']=interiors(page,output)
                report['floors']=floors(page,output)
                report['replacement']=replace(page,output)
                report['dialogSafety']=dialog_safety(page)
                report['renderChecks']=render_viewports(page,output)
                assert not report['pageErrors'],report['pageErrors']
                report['status']='passed'
            finally:
                if report['status']!='passed':page.screenshot(path=str(output/'failure.png'))
                browser.close()
    except Exception as exc:
        report.update(status='failed',error=str(exc));raise
    finally:
        server.should_exit=True;thread.join(timeout=15)
        (output/'report.json').write_text(json.dumps(report,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output');parser.add_argument('--serve',action='store_true');parser.add_argument('--port',type=int,default=0)
    args=parser.parse_args();output=Path(args.output);output.mkdir(parents=True,exist_ok=True)
    port=args.port
    if not port:
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
    if args.serve:uvicorn.run(build_app(output),host='127.0.0.1',port=port,log_level='error')
    else:verify(output,port)
