"""Real cooling-tower and shared-avatar browser acceptance, isolated backend."""
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
OUT = ROOT / '.runtime' / ('process-operator-' + time.strftime('%Y%m%d-%H%M%S'))
PORT = 8499
BASE = f'http://127.0.0.1:{PORT}'
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def main():
    with socket.socket() as s:
        s.bind(('127.0.0.1', PORT))
    subprocess.run([sys.executable,'desktop/tools/prepare-application-check.py','--destination',str(OUT),'--port',str(PORT)],
                   cwd=ROOT,check=True,creationflags=HIDDEN)
    source = ROOT / 'generated/training/process/cooling-tower/cooling_tower_body.glb'
    original = hashlib.sha256(source.read_bytes()).hexdigest()
    report = {'status':'running','errors':[],'mutations':[],'captures':[]}
    def stage(name):
        report['stage']=name
        (OUT / 'result.json').write_text(json.dumps(report,indent=2))
        print(name,flush=True)
    env = dict(os.environ,INSPECTORPRO_FACILITY_LAYOUT_ROOT=str(OUT/'facility'))
    with (OUT/'server.log').open('w') as log:
        server=subprocess.Popen([sys.executable,'-m','uvicorn','server:app','--host','127.0.0.1','--port',str(PORT)],
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
                page=browser.new_page(viewport={'width':1600,'height':960})
                page.set_default_timeout(60000)
                page.on('pageerror',lambda e:report['errors'].append(str(e)))
                page.on('console',lambda e:report['errors'].append(e.text) if 'Shader Error' in e.text else None)
                page.on('request',lambda r:report['mutations'].append({'url':r.url,'method':r.method})
                        if r.method in ('POST','PUT','DELETE') and '/api/facility-layouts/' in r.url else None)
                # No provider requests are needed to qualify animation and timeline wiring.
                page.route('**/api/voice/synthesize',lambda r:r.fulfill(status=503,body='Voice excluded from this visual check'))
                try:
                    stage('tower-load')
                    page.goto(BASE,wait_until='domcontentloaded',timeout=120000)
                    page.get_by_role('tab',name='Workflows',exact=True).click()
                    page.select_option('#trainingTypeRibbonSelect','plant_process')
                    page.wait_for_function('state.assyLiveScene && _trainPlantSpatialWalk.geometry && window.InspectorProProcessOperator',timeout=120000)
                    report['geometry']=page.evaluate('''() => {const g=_trainPlantSpatialWalk.geometry;return {
                        modelScale:g.modelScale,surfaces:g.walkSurfaces,obstacleCount:g.obstacleVolumes.length};}''')
                    geometry=page.evaluate('''() => {const g=_trainPlantSpatialWalk.geometry;return {...g,
                        filterBox:_trainPlantBoundsForGroups(['existing_cooling_tower_filter_vessel'])};}''')
                    (OUT/'geometry.json').write_text(json.dumps(geometry))
                    before=page.evaluate('({position:state.assyCamera.position.toArray(),target:state.assyControls.target.toArray()})')
                    page.locator('[data-plant-process-command="walkthrough"]').click()
                    page.wait_for_function('_trainPlantSpatialWalk.locked && _trainPlantSpatialWalk.avatar')
                    if '--framing-only' in sys.argv:
                        stage('framing-followup')
                        page.keyboard.press('Escape')
                        page.wait_for_function('!_trainPlantSpatialWalk.active')
                        page.evaluate('''() => {
                            _trainApplyPlantOperatorView(['step_tangga_grating','tangga_rev_03_1','handrail_tangga'],'Stairs','stair-access');
                            _trainEnterPlantSpatialWalkthrough({guided:true});
                            const r=_trainPlantSpatialWalk,p=_trainPlantBoundsForGroups(['existing_cooling_tower_filter_vessel']).getCenter(new THREE.Vector3());
                            const dx=p.x-r.position.x,dz=p.z-r.position.z;
                            r.yaw=r.avatarHeading=Math.atan2(-dx,-dz);
                            r.pitch=Math.atan2(p.y-r.footY-r.currentEyeHeight,Math.hypot(dx,dz));
                            _trainApplyPlantWalkOrientation();_trainSyncPlantOperator(.25,0);
                        }''')
                        for width,height in [(1600,960),(900,700)]:
                            page.set_viewport_size({'width':width,'height':height})
                            page.wait_for_function('''() => {const c=document.getElementById('assy-3d-container'),v=state.assyRenderer.domElement;
                                return Math.abs(v.clientWidth-c.clientWidth)<1 && Math.abs(v.clientHeight-c.clientHeight)<1
                                    && Math.abs(state.assyCamera.aspect-c.clientWidth/c.clientHeight)<.001;}''')
                            mark=page.evaluate('performance.now()')
                            page.wait_for_function('(t)=>_trainPlantSpatialWalk.lastTime>t',arg=mark)
                            metrics=page.evaluate('''() => {const r=_trainPlantSpatialWalk,c=r.container.getBoundingClientRect(),
                                h=r.hud.getBoundingClientRect();return {width:innerWidth,height:innerHeight,
                                container:{left:c.left,top:c.top,right:c.right,bottom:c.bottom,width:c.width,height:c.height},
                                hudInside:h.left>=c.left&&h.right<=c.right&&h.top>=c.top&&h.bottom<=c.bottom,
                                avatarVisible:r.avatar.root.visible,camera:state.assyCamera.position.toArray(),position:r.position};}''')
                            report['captures'].append(metrics)
                            page.screenshot(path=str(OUT/f'framing-{width}.png'))
                            assert metrics['hudInside']
                            assert metrics['container']['bottom']<=height and metrics['container']['right']<=width
                        body=page.evaluate('JSON.stringify(_trainPlantSpatialWalk.position)')
                        page.evaluate('''() => {const input=document.createElement('textarea');input.id='operator-typing-probe';
                            document.body.appendChild(input);input.focus();}''')
                        page.keyboard.type('wasd c kz ')
                        assert page.locator('#operator-typing-probe').input_value()=='wasd c kz '
                        assert page.evaluate('JSON.stringify(_trainPlantSpatialWalk.position)')==body
                        page.evaluate("document.getElementById('operator-typing-probe').remove()")
                        page.evaluate('''() => {_trainPlantSpatialWalk.pendingCue={step:{processZone:'controls_safety'}};
                            _trainCancelPlantOperatorGuide();}''')
                        assert page.evaluate('_trainPlantSpatialWalk.pendingCue===null')
                        page.evaluate("switchTab('drawing')")
                        assert page.evaluate("!_trainStartPlantOperatorGuide({groups:['existing_cooling_tower_filter_vessel']})")
                        page.evaluate('_trainDisposeLiveAssemblyViewer()')
                        assert page.evaluate('!_trainPlantSpatialWalk.avatar && !_trainPlantSpatialWalk.cueProcedure && !_trainPlantSpatialWalk.listenersAttached')
                        assert not report['errors'] and not report['mutations']
                        report['status']='passed';stage('complete');return
                    stage('poses')
                    for key,posture in [('Space','standing'),('c','crouching'),('k','kneeling'),('z','crawling'),('Space','standing')]:
                        stage('pose-'+posture)
                        page.keyboard.press(key)
                        page.wait_for_function('(p)=>_trainPlantSpatialWalk.postureMessage || (_trainPlantSpatialWalk.posture===p && _trainPlantSpatialWalk.avatar.snapshot().postureBlend>.999)',arg=posture)
                        assert page.evaluate('_trainPlantSpatialWalk.posture')==posture
                        page.evaluate('''() => {const r=_trainPlantSpatialWalk;r.yaw=r.avatarHeading-.8;_trainApplyPlantWalkOrientation();}''')
                        path=OUT/f'{posture}.png'
                        page.locator('#assy-3d-container canvas').first.screenshot(path=str(path))
                        pose=page.evaluate('''() => {const r=_trainPlantSpatialWalk;r.avatar.root.updateMatrixWorld(true);
                            const b=new THREE.Box3(),v=new THREE.Vector3();r.avatar.root.traverse(m=>{
                                if(!m.isMesh)return;const p=m.geometry.attributes.position;
                                for(let i=0;i<p.count;i++){v.fromBufferAttribute(p,i);
                                    if(m.isSkinnedMesh)m.boneTransform(i,v);b.expandByPoint(v.applyMatrix4(m.matrixWorld));}
                            });return {
                                ...r.avatar.snapshot(),min:b.min,max:b.max,position:r.position};}''')
                        assert pose['visible'], posture
                        assert pose['min']['y'] >= pose['position']['y']-.04, pose
                        report['captures'].append(pose)
                        with Image.open(path) as im:
                            assert len(set(im.resize((240,160)).convert('RGB').getdata()))>100
                    body=page.evaluate('JSON.stringify(_trainPlantSpatialWalk.position)')
                    page.keyboard.press('v')
                    assert page.evaluate('_trainPlantSpatialWalk.cameraMode')=='first-person'
                    assert not page.evaluate('_trainPlantSpatialWalk.avatar.root.visible')
                    page.keyboard.press('v')
                    assert page.evaluate('JSON.stringify(_trainPlantSpatialWalk.position)')==body
                    page.keyboard.press('Escape')
                    page.wait_for_function('!_trainPlantSpatialWalk.active')
                    assert page.evaluate('({position:state.assyCamera.position.toArray(),target:state.assyControls.target.toArray()})')==before
                    stage('stair-climb')
                    page.evaluate("_trainApplyPlantOperatorView(['step_tangga_grating','tangga_rev_03_1','handrail_tangga'],'Stairs','stair-access')")
                    page.locator('[data-plant-process-command="walkthrough"]').click()
                    page.wait_for_function('_trainPlantSpatialWalk.locked')
                    page.keyboard.down('w')
                    page.wait_for_function('_trainPlantSpatialWalk.surfaceKind === "platform"',timeout=60000)
                    page.keyboard.up('w')
                    page.wait_for_function('_trainPlantSpatialWalk.avatar.snapshot().animation === "idle"')
                    report['platform']=page.evaluate('({y:_trainPlantSpatialWalk.footY,floor:_trainPlantSpatialWalk.geometry.floorY,surface:_trainPlantSpatialWalk.surfaceId})')
                    assert report['platform']['y']-report['platform']['floor']>1
                    page.locator('#assy-3d-container canvas').first.screenshot(path=str(OUT/'platform.png'))
                    page.keyboard.down('s')
                    page.wait_for_function('_trainPlantSpatialWalk.surfaceKind === "ground"',timeout=60000)
                    page.keyboard.up('s')
                    page.keyboard.press('Escape')
                    page.wait_for_function('!_trainPlantSpatialWalk.active')
                    stage('guide-timeline')
                    page.locator('[data-plant-process-command="operator-guide"]').click()
                    page.wait_for_function('_trainPlantSpatialWalk.guide')
                    report['guideStart']=page.evaluate('_trainPlantSpatialWalk.guide.snapshot()')
                    page.wait_for_function('_trainPlantSpatialWalk.guide.snapshot().index>0',timeout=45000)
                    page.locator('[data-plant-process-command="operator-guide"]').click()
                    frozen=page.evaluate('JSON.stringify({p:_trainPlantSpatialWalk.position,avatar:_trainPlantSpatialWalk.avatar.snapshot(),guide:_trainPlantSpatialWalk.guide.snapshot()})')
                    page.wait_for_timeout(250)
                    assert page.evaluate('JSON.stringify({p:_trainPlantSpatialWalk.position,avatar:_trainPlantSpatialWalk.avatar.snapshot(),guide:_trainPlantSpatialWalk.guide.snapshot()})')==frozen
                    page.evaluate('''() => {const input=document.createElement('textarea');input.id='operator-typing-probe';
                        document.body.appendChild(input);input.focus();}''')
                    page.keyboard.type('wasd c kz ')
                    assert page.locator('#operator-typing-probe').input_value()=='wasd c kz '
                    assert page.evaluate('JSON.stringify({p:_trainPlantSpatialWalk.position,avatar:_trainPlantSpatialWalk.avatar.snapshot(),guide:_trainPlantSpatialWalk.guide.snapshot()})')==frozen
                    page.evaluate("document.getElementById('operator-typing-probe').remove()")
                    page.locator('[data-plant-process-command="operator-guide"]').click()
                    page.wait_for_function('_trainPlantSpatialWalk.guide.snapshot().status === "complete" || _trainPlantSpatialWalk.guide.snapshot().status === "blocked"',timeout=180000)
                    report['guideEnd']=page.evaluate('_trainPlantSpatialWalk.guide.snapshot()')
                    assert report['guideEnd']['status']=='complete',report['guideEnd']
                    page.set_viewport_size({'width':900,'height':700})
                    page.locator('#assy-3d-container canvas').first.screenshot(path=str(OUT/'narrow.png'))
                    report['narrowHud']=page.evaluate('''() => {const a=document.querySelector('.train-plant-walkthrough-hud').getBoundingClientRect();
                        const b=document.getElementById('assy-3d-container').getBoundingClientRect();
                        return {inside:a.left>=b.left&&a.right<=b.right&&a.top>=b.top&&a.bottom<=b.bottom,height:a.height};}''')
                    assert report['narrowHud']['inside']
                    stage('step-and-cleanup')
                    page.evaluate('''() => {trainingState.procedure={trainingType:'plant_process',steps:[
                        {processZone:'controls_safety',instruction:'Inspect the filter from the exterior.'},
                        {processZone:'warm_return',instruction:'Observe the inlet.'}]};
                        trainingState.isPlaying=true;_trainStepGoto(0);}''')
                    page.wait_for_function('_trainPlantSpatialWalk.guideSource === "training" && _trainPlantSpatialWalk.guide')
                    page.evaluate('trainingState.isPlaying=false')
                    page.wait_for_function('_trainPlantSpatialWalk.guide.snapshot().status === "paused"')
                    page.evaluate('_trainStepGoto(1)')
                    assert page.evaluate('_trainPlantSpatialWalk.cueKey')=='1:warm_return'
                    page.evaluate('_trainDisposeLiveAssemblyViewer()')
                    assert page.evaluate('!_trainPlantSpatialWalk.avatar && !_trainPlantSpatialWalk.guide && !_trainPlantSpatialWalk.listenersAttached')
                    assert not report['errors'],report['errors']
                    assert not report['mutations']
                    report['status']='passed'
                    stage('complete')
                except Exception as e:
                    report['status']='failed';report['error']=str(e)
                    page.screenshot(path=str(OUT/'failure.png'))
                    report['failureState']=page.evaluate('''() => {const r=_trainPlantSpatialWalk;return {
                        active:r.active,posture:r.posture,position:r.position,message:r.postureMessage,
                        surface:r.surfaceKind,keys:[...r.keys],frameTravel:r.frameTravel,
                        guide:r.guide&&r.guide.snapshot(),avatar:r.avatar&&r.avatar.snapshot()};}''')
                    raise
                finally:
                    browser.close()
        finally:
            server.terminate()
            try:server.wait(timeout=15)
            except subprocess.TimeoutExpired:server.kill();server.wait(timeout=10)
            report['backendStopped']=server.poll() is not None
            report['sourceUnchanged']=hashlib.sha256(source.read_bytes()).hexdigest()==original
            source_record=json.loads((OUT/'application-check-source.json').read_text())
            report['manualLayoutUnchanged']=hashlib.sha256(Path(source_record['originalPath']).read_bytes()).hexdigest()==source_record['originalSha256']
            (OUT/'result.json').write_text(json.dumps(report,indent=2))
            print(str(OUT),flush=True)


if __name__=='__main__':main()
