"""Real manual-layout and cooling-tower camera settings, no Save or providers."""
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.request
from PIL import Image
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime' / ('walk-camera-' + time.strftime('%Y%m%d-%H%M%S'))
PORT = 8497
BASE = f'http://127.0.0.1:{PORT}'
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
APP = '_trainFacilityLayoutAuthoringApp'
A = APP + '.workspace.threeAdapter'


def main():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', PORT))
    subprocess.run([sys.executable, 'desktop/tools/prepare-application-check.py', '--destination', str(OUT), '--port', str(PORT)],
                   cwd=ROOT, check=True, creationflags=HIDDEN)
    source = json.loads((OUT/'application-check-source.json').read_text())
    report = {'status':'running','errors':[],'mutations':[],'captures':[]}
    def stage(name):
        report['stage'] = name
        (OUT/'result.json').write_text(json.dumps(report,indent=2))
        try: print(name,flush=True)
        except OSError: pass
    env = dict(os.environ, INSPECTORPRO_FACILITY_LAYOUT_ROOT=str(OUT/'facility'), INSPECTORPRO_INDUSTRIAL_ASSET_LIBRARY='1')
    for flag in ['VIEWER_V2','MANUAL_EDIT','CONSTRAINTS','ROUTING']:
        env['INSPECTORPRO_FACILITY_LAYOUT_'+flag] = '1'
    with (OUT/'server.log').open('w') as log:
        server = subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(PORT)],
                                  cwd=ROOT,env=env,stdout=log,stderr=log,creationflags=HIDDEN)
        try:
            stage('backend-start')
            deadline=time.monotonic()+120
            while True:
                try:
                    urllib.request.urlopen(BASE+'/api/facility-layout-bootstrap',timeout=3).close()
                    break
                except Exception:
                    if server.poll() is not None or time.monotonic()>deadline: raise RuntimeError('Backend startup failed')
                    time.sleep(.5)
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True)
                page=browser.new_page(viewport={'width':1440,'height':900})
                page.set_default_timeout(90000)
                page.on('pageerror',lambda e:report['errors'].append(str(e)))
                page.on('console',lambda e:report['errors'].append(e.text) if 'Shader Error' in e.text else None)
                page.on('request',lambda r:report['mutations'].append(r.url) if r.method in ('POST','PUT','DELETE') and '/api/facility-layouts/' in r.url else None)
                page.route('**/api/voice/synthesize',lambda r:r.fulfill(status=503,body='Not part of camera check'))
                def capture(name):
                    path=OUT/(name+'.png')
                    page.screenshot(path=str(path))
                    with Image.open(path) as im:
                        assert len(im.convert('RGB').getcolors(im.width*im.height) or [])>100
                    report['captures'].append(name)
                def control(selector):
                    button=page.locator(selector)
                    button.click()
                    panel=page.locator('.ip-walk-camera-panel:not([hidden])')
                    panel.wait_for(state='visible')
                    for name,distance in [('close',3),('standard',5),('wide',9)]:
                        panel.locator('[data-camera-preset="'+name+'"]').click()
                        assert float(panel.get_by_label('Follow distance',exact=True).input_value())==distance
                    slider=panel.get_by_label('Follow distance',exact=True)
                    slider.focus();page.keyboard.press('ArrowRight')
                    assert float(slider.input_value())>9
                    rise=panel.get_by_label('Camera rise',exact=True)
                    rise.focus();page.keyboard.press('ArrowRight')
                    assert float(rise.input_value())>1.5
                    panel.get_by_label('Reset camera settings',exact=True).click()
                    assert float(slider.input_value())==5 and float(rise.input_value())==.5
                    panel.locator('[data-camera-preset="wide"]').click()
                    rect=panel.bounding_box(); size=page.viewport_size
                    assert rect['x']>=0 and rect['y']>=0
                    assert rect['x']+rect['width']<=size['width'] and rect['y']+rect['height']<=size['height']
                    capture(report['stage'])
                    page.keyboard.press('Escape')
                    assert panel.count()==0
                    assert button.evaluate('(el)=>document.activeElement===el')
                try:
                    stage('manual-load')
                    page.goto(BASE+'/?facilityLayoutId=fl-reference-manual-20260812',wait_until='domcontentloaded',timeout=120000)
                    page.get_by_role('tab',name='Workflows',exact=True).click()
                    page.select_option('#trainingTypeRibbonSelect','facility_layout')
                    page.wait_for_function('window.'+APP+'?.session.getState().loaded',timeout=150000)
                    original=page.evaluate(APP+'.session.getState()')
                    assert len(original['layout']['placements'])==827
                    saved=OUT/'facility/layouts/local/site-local/layouts'/ (original['layout']['layoutId']+'.json')
                    saved_hash=hashlib.sha256(saved.read_bytes()).hexdigest()
                    page.locator('#trainFacilityLayoutAuthoring [data-view="3d"]').click()
                    page.wait_for_function(A+'.getDiagnostics().pendingLoads===0 && '+A+'.getDiagnostics().assetGroupCount>0',timeout=180000)
                    assert not page.evaluate(A+'.getDiagnostics().degraded')
                    for width,height in [(1440,900),(900,700)]:
                        page.set_viewport_size({'width':width,'height':height})
                        stage('facility-settings-'+str(width))
                        control('[data-three-command="camera-settings"]')
                    page.set_viewport_size({'width':1440,'height':900})
                    route=next(r for r in original['layout']['routes'] if r['label']=='Main Forklift Boulevard')
                    a,b=route['centerline'][0],route['centerline'][-1]
                    spawn={k:a[k]*.7+b[k]*.3 for k in ('x','y','z')}
                    page.evaluate('''(point)=>{const a='''+A+''',v=a.getCameraView();
                        v.position={x:point.x-10,y:point.y+3,z:point.z};v.target={...point};
                        a.applyCameraView(v);a.setWalkthroughCameraMode('third-person');
                        a.enterWalkthrough({ignoreSelection:true,worldPoint:point});}''',spawn)
                    page.wait_for_function(A+'.getWalkthroughState().locked')
                    state=lambda:page.evaluate(A+'.getWalkthroughState()')
                    body=state()['position']
                    report['facilityPresets']={}
                    for name in ['close','standard','wide']:
                        page.evaluate('(k)=>'+A+'.setWalkthroughCameraSettings(InspectorProWalkthroughCamera.PRESETS[k])',name)
                        page.wait_for_function('!'+A+'.getDiagnostics().demandRendering.pendingFrame')
                        snapshot=state()
                        assert snapshot['position']==body and snapshot['avatar']['visible']
                        assert not snapshot['cameraObstructed'],snapshot
                        height=page.evaluate('''()=>{const a='''+A+''',p=a.getWalkthroughState().position;
                            return a.worldToClient(p).y-a.worldToClient({...p,y:p.y+1.876}).y;}''')
                        report['facilityPresets'][name]={'heightPixels':height,'state':snapshot}
                        capture('facility-'+name)
                    assert report['facilityPresets']['close']['heightPixels']>report['facilityPresets']['wide']['heightPixels']*2
                    # Mouse-look must not accumulate the raised render-camera pitch.
                    before=page.evaluate(A+'.getDiagnostics().camera.quaternion')
                    page.evaluate("()=>{for(let i=0;i<20;i++)document.dispatchEvent(new MouseEvent('mousemove',{movementX:0,movementY:0,bubbles:true}));}")
                    after=page.evaluate(A+'.getDiagnostics().camera.quaternion')
                    assert max(abs(before[k]-after[k]) for k in before)<1e-6
                    page.mouse.wheel(0,-100)
                    page.wait_for_function(A+'.getWalkthroughState().cameraSettings.distance < 9')
                    assert state()['position']==body
                    report['wheelPreference']=state()['cameraSettings']
                    page.keyboard.press('c')
                    first=state()['cameraSettings']
                    page.mouse.wheel(0,100)
                    assert state()['cameraSettings']==first
                    page.keyboard.press('c')
                    page.keyboard.down('w')
                    page.wait_for_function(A+'.getWalkthroughState().avatar.distanceMeters>.3')
                    page.keyboard.up('w')
                    page.wait_for_function(A+'.getWalkthroughState().avatar.animation==="idle"')
                    capture('facility-moving-wide')
                    page.evaluate(A+'.exitWalkthrough("camera-check")')
                    final=page.evaluate(APP+'.session.getState()')
                    for key in ('layout','selection','history','historyCursor','baseRevision','draftRevision','dirty'):
                        assert final[key]==original[key],key
                    assert hashlib.sha256(saved.read_bytes()).hexdigest()==saved_hash
                    stage('reload-persistence')
                    preference=page.evaluate('InspectorProWalkthroughCamera.load()')
                    # Reload the application without re-requesting the heavy facility scene.
                    page.goto(BASE,wait_until='domcontentloaded',timeout=120000)
                    page.wait_for_function('window.InspectorProWalkthroughCamera')
                    assert page.evaluate('InspectorProWalkthroughCamera.load()')==preference
                    stage('tower-load')
                    page.get_by_role('tab',name='Workflows',exact=True).click()
                    page.select_option('#trainingTypeRibbonSelect','plant_process')
                    page.wait_for_function('state.assyLiveScene && _trainPlantSpatialWalk.geometry',timeout=150000)
                    assert page.evaluate('_trainPlantSpatialWalk.cameraSettings')==preference
                    for width,height in [(1440,900),(900,700)]:
                        page.set_viewport_size({'width':width,'height':height})
                        stage('process-settings-'+str(width))
                        control('[data-plant-process-command="camera-settings"]')
                    page.set_viewport_size({'width':1440,'height':900})
                    page.evaluate('''()=>{_trainApplyPlantOperatorView(['step_tangga_grating','tangga_rev_03_1','handrail_tangga'],'Stairs','stair-access');
                        _trainEnterPlantSpatialWalkthrough({guided:true});
                        const r=_trainPlantSpatialWalk,p=_trainPlantBoundsForGroups(['existing_cooling_tower_filter_vessel']).getCenter(new THREE.Vector3());
                        r.yaw=r.avatarHeading=Math.atan2(-(p.x-r.position.x),-(p.z-r.position.z));r.pitch=-.1;
                        _trainApplyPlantWalkOrientation();_trainSyncPlantOperator(.25,0);}''')
                    body=page.evaluate('({..._trainPlantSpatialWalk.position})')
                    report['processPresets']={}
                    for name in ['close','standard','wide']:
                        page.evaluate('(k)=>_trainSetPlantCameraSettings(InspectorProWalkthroughCamera.PRESETS[k])',name)
                        page.wait_for_function('_trainPlantSpatialWalk.avatar.root.visible')
                        result=page.evaluate('''()=>{const r=_trainPlantSpatialWalk,c=state.assyCamera,s=r.geometry.modelScale;
                            const feet=new THREE.Vector3(r.position.x,r.footY,r.position.z).project(c);
                            const head=new THREE.Vector3(r.position.x,r.footY+1.876*s,r.position.z).project(c);
                            return {position:r.position,settings:r.cameraSettings,camera:c.position.toArray(),
                                heightPixels:(head.y-feet.y)*state.assyRenderer.domElement.clientHeight/2};}''')
                        assert result['position']==body
                        report['processPresets'][name]=result
                        capture('process-'+name)
                    assert report['processPresets']['close']['heightPixels']>report['processPresets']['wide']['heightPixels']*1.5
                    canvas=page.locator('#assy-3d-container canvas').first
                    canvas.hover();page.mouse.wheel(0,-100)
                    page.wait_for_function('_trainPlantSpatialWalk.cameraSettings.distance<9')
                    assert page.evaluate('({..._trainPlantSpatialWalk.position})')==body
                    page.keyboard.press('v')
                    assert not page.evaluate('_trainPlantSpatialWalk.avatar.root.visible')
                    preference=page.evaluate('_trainPlantSpatialWalk.cameraSettings')
                    page.mouse.wheel(0,100)
                    assert page.evaluate('_trainPlantSpatialWalk.cameraSettings')==preference
                    page.keyboard.press('v')
                    for width,height in [(1440,900),(900,700)]:
                        page.set_viewport_size({'width':width,'height':height})
                        page.wait_for_function('''()=>{const r=state.assyRenderer.domElement,c=document.getElementById('assy-3d-container');
                            return r.clientHeight===c.clientHeight && Math.abs(state.assyCamera.aspect-c.clientWidth/c.clientHeight)<.001;}''')
                        capture('process-wide-'+str(width))
                        assert page.evaluate('''()=>{const r=_trainPlantSpatialWalk,c=r.container.getBoundingClientRect(),h=r.hud.getBoundingClientRect();
                            return c.bottom<=innerHeight && h.bottom<=c.bottom && h.right<=c.right;}''')
                    page.evaluate('_trainDisposeLiveAssemblyViewer()')
                    assert page.evaluate('!_trainPlantSpatialWalk.cameraControl && !_trainPlantSpatialWalk.avatar && !_trainPlantSpatialWalk.listenersAttached')
                    assert page.locator('.ip-walk-camera-panel:not([hidden])').count()==0
                    assert not report['errors'],report['errors']
                    assert not report['mutations'],report['mutations']
                    report['status']='passed';stage('complete')
                except Exception as e:
                    report.update(status='failed',error=repr(e))
                    capture('failure')
                    raise
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=15)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
            report['backendStopped']=server.poll() is not None
            report['manualLayoutUnchanged']=hashlib.sha256(Path(source['originalPath']).read_bytes()).hexdigest()==source['originalSha256']
            (OUT/'result.json').write_text(json.dumps(report,indent=2))
            try: print(str(OUT),flush=True)
            except OSError: pass


if __name__=='__main__':main()
