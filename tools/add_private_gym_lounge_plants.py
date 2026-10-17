"""Place four existing decorative plants without changing lounge furniture or play space."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'
from playwright.sync_api import sync_playwright
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from tools.build_private_gym import STORE

OUT = ROOT/'.runtime/private-gym-lounge-plants-20261010'
TARGET = STORE/'layouts/local/site-local/layouts/fl-private-gym-20261007.json'
APP = 'window._trainFacilityLayoutAuthoringApp'
ASSET = 'asset-gym-patio-plant'
POSITIONS = [(0.8,-3.9),(20.9,-4.2),(20.9,-16.95),(0.8,-17.05)]
LABELS = {f'Lounge Decorative Plant {i}' for i in range(1,5)}


def write(name, value):
    (OUT/name).write_text(json.dumps(value,indent=2),encoding='utf8')


def audit(before, after):
    old = {p['placementId']:p for p in before['placements']}
    current = {p['placementId']:p for p in after['placements']}
    assert all(current.get(k)==v for k,v in old.items()), 'Existing furniture changed'
    added = [p for k,p in current.items() if k not in old]
    assert len(added)==4 and {p['metadata']['instanceLabel'] for p in added}==LABELS
    assert all(p['assetId']==ASSET and p['transform']['scale']==1 for p in added)
    for i,p in enumerate(sorted(added,key=lambda p:p['metadata']['instanceLabel'])):
        assert p['transform']['position']==dict(x=POSITIONS[i][0],y=0,z=POSITIONS[i][1])
    left,right = deepcopy(before),deepcopy(after)
    for value in (left,right):
        value.pop('placements'); value.pop('updatedAt')
    assert left==right, 'Unrelated document content changed'
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['draft','review','save'])
    phase=parser.parse_args().phase
    OUT.mkdir(parents=True,exist_ok=True)
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        page=next(v for c in browser.contexts for v in c.pages if v.url.startswith('http://127.0.0.1:8480/'))
        page.wait_for_function(APP+'?.session?.getState().loaded',timeout=120000)
        state=page.evaluate(APP+'.session.getState()')
        assert state['layout']['layoutId']=='fl-private-gym-20261007'
        raw=TARGET.read_bytes()
        if phase=='draft':
            assert not state['dirty'] and state['layout']==json.loads(raw), 'Unsaved user changes exist'
            assert not any(p.get('metadata',{}).get('instanceLabel') in LABELS for p in state['layout']['placements'])
            backup=OUT/'before.json'
            if backup.exists():
                assert backup.read_bytes()==raw
            else:
                backup.write_bytes(raw)
            write('layout-hashes.json',{p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in TARGET.parent.glob('*.json')})
            draft=page.evaluate('''async positions=>{
                const a=window._trainFacilityLayoutAuthoringApp,s=a.session;
                const asset=a.workspace.assetCatalog.find(v=>v.assetId==='asset-gym-patio-plant').source;
                const b=asset.definition.geometry.aabb;
                if(b.maximum.x-b.minimum.x>.6||b.maximum.z-b.minimum.z>.6)throw Error('Plant footprint changed');
                await s.placeAssets(positions.map(([x,z],i)=>({assetId:asset.assetId,
                    assetDefinitionRevision:asset.assetDefinitionRevision,position:{x,y:0,z},
                    quaternion:{x:0,y:0,z:0,w:1},scale:1,
                    metadata:{instanceLabel:'Lounge Decorative Plant '+(i+1),room:'lounge',gymRole:'decor',
                        inputMethod:'independent-authoring',scaleEvidence:'Existing library scale; unitless STL provisionally interpreted as centimetres'}})));
                s.clearSelection();return s.getState().layout;
            }''',POSITIONS)
            added=audit(json.loads(raw),draft)
            assert TARGET.read_bytes()==raw
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                spatial=host.service._diagnose_spatial(host.principal(),'site-local',draft)
                host.service._require_spatially_valid(spatial)
            finally:
                host.close()
            write('spatial.json',spatial)
            write('draft.json',draft)
            write('placement-check.json',dict(status='draft',placements=added,existingLayoutUnchanged=True))
        elif phase=='save':
            before=(OUT/'before.json').read_bytes()
            draft=json.loads((OUT/'draft.json').read_bytes())
            proof=json.loads((OUT/'visual-review.json').read_bytes())
            assert proof['status']=='passed' and proof['draftSha256']==hashlib.sha256((OUT/'draft.json').read_bytes()).hexdigest()
            assert raw==before and state['layout']==draft, 'Layout changed since review'
            page.evaluate(APP+'.session.save()')
            page.wait_for_function('!'+APP+'.session.getState().dirty',timeout=30000)
            saved=page.evaluate(APP+'.session.getState().layout')
            audit(json.loads(before),saved)
            assert json.loads(TARGET.read_bytes())==saved
            hashes=json.loads((OUT/'layout-hashes.json').read_bytes())
            assert all(hashlib.sha256((TARGET.parent/n).read_bytes()).hexdigest()==h for n,h in hashes.items()
                if n not in (TARGET.name,'registry.json'))
            write('saved.json',saved)
            write('save-check.json',dict(status='saved',otherLayoutsUnchanged=True,desktopMatchesSaved=True,updatedAt=saved['updatedAt']))
            print('saved')
            return
        else:
            assert raw==(OUT/'before.json').read_bytes()
            assert state['layout']==json.loads((OUT/'draft.json').read_bytes())
        page.evaluate(APP+".workspace._setViewMode('3d')")
        page.evaluate(APP+".workspace.threeAdapter.exitWalkthrough('lounge-plants-review')")
        page.wait_for_function(APP+'.workspace.threeAdapter.getDiagnostics().pendingLoads===0',timeout=120000)
        page.wait_for_timeout(500)
        for name,position,target in [('plant-detail',(2.5,1.8,-5.6),(.8,.75,-3.9)),
                ('seating',(7,2.8,-8.9),(1.4,1,-4.8)),
                ('arcade',(6,2.8,-13.9),(1,1,-16.5)),('games',(14,3,-10.5),(20.9,1,-16)),
                ('lounge-overview',(12,14,-10),(11,0,-11))]:
            page.evaluate('([position,target])=>{const a='+APP+'.workspace.threeAdapter,v=a.getCameraView();Object.assign(v,{position,target,up:{x:0,y:1,z:0},fov:65,near:.05,far:250});a.applyCameraView(v)}',
                [dict(zip('xyz',position)),dict(zip('xyz',target))])
            page.wait_for_function('id=>'+APP+'.workspace.threeAdapter.getDiagnostics().representationGroups.some(g=>g.assetId===id&&["overview","detail"].includes(g.representation))',arg=ASSET,timeout=120000)
            page.wait_for_timeout(400)
            page.screenshot(path=str(OUT/(name+'.png')),timeout=20000)
        diagnostics=page.evaluate(APP+'.workspace.threeAdapter.getDiagnostics()')
        assert not diagnostics['warnings'],diagnostics['warnings']
        write('desktop-render-check.json',dict(status='passed',warnings=[],groups=[g for g in diagnostics['representationGroups'] if g['assetId']==ASSET]))
        print(phase)


if __name__=='__main__':
    main()
