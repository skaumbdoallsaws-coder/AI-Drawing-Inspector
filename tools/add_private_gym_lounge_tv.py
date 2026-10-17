"""Add the lounge TV through the desktop editor; save only after visual review."""
import argparse
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path.home() / 'AppData/Roaming/Python/Python314/site-packages'))
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'
from playwright.sync_api import sync_playwright

OUT = ROOT / '.runtime/private-gym-tv-20261010'
TARGET = ROOT / '.runtime/facility-layout/layouts/local/site-local/layouts/fl-private-gym-20261007.json'
APP = 'window._trainFacilityLayoutAuthoringApp'
LABELS = {'Lounge TV Console', 'Lounge TV'}


def audit(before, after):
    old = {p['placementId']: p for p in before['placements']}
    current = {p['placementId']: p for p in after['placements']}
    assert all(current.get(k) == v for k, v in old.items()), 'Existing placement changed'
    added = [p for k, p in current.items() if k not in old]
    assert len(added) == 2 and {p['metadata']['instanceLabel'] for p in added} == LABELS
    assert all(p['transform']['scale'] == 1 for p in added)
    a, b = deepcopy(before), deepcopy(after)
    for value in (a, b):
        value.pop('placements')
        value.pop('updatedAt')
    assert a == b, 'Existing rooms, artwork or other layout content changed'
    return added


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['draft', 'save'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9542', timeout=20000)
        page = next(v for c in browser.contexts for v in c.pages if v.url.startswith('http://127.0.0.1:8480/'))
        page.wait_for_function(APP + '?.session?.getState().loaded', timeout=120000)
        state = page.evaluate(APP + '.session.getState()')
        assert state['layout']['layoutId'] == 'fl-private-gym-20261007'
        raw = TARGET.read_bytes()
        if args.phase == 'draft':
            assert not state['dirty'] and state['layout'] == json.loads(raw)
            assert not any(p['metadata'].get('instanceLabel') in LABELS for p in state['layout']['placements'])
            backup = OUT / 'layout-before.json'
            if backup.exists():
                assert backup.read_bytes() == raw, 'Saved base changed'
            else:
                backup.write_bytes(raw)
            write('layout-hashes.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in TARGET.parent.glob('*.json')})
            result = page.evaluate('''async()=>{
                const a=window._trainFacilityLayoutAuthoringApp,s=a.session,state=s.getState();
                const catalog=new Map(a.workspace.assetCatalog.map(v=>[v.assetId,v.source]));
                const wall=state.layout.placements.find(v=>v.placementId==='pl-gym-wellness-lounge-north-left');
                const box=catalog.get(wall.assetId).definition.geometry.aabb;
                if(JSON.stringify(wall.transform.quaternion)!==JSON.stringify({w:1,x:0,y:0,z:0})) throw Error('Wall orientation changed');
                const x=3.6, gap=.02, wallFace=wall.transform.position.z+box.minimum.z;
                const consoleAsset=catalog.get('asset-gym-lounge-tv-unit'),tv=catalog.get('asset-breakroom-conference-screen');
                const common={quaternion:{x:0,y:1,z:0,w:0},scale:1,positionMode:'manual'};
                const metadata=label=>({instanceLabel:label,room:'lounge',gymRole:'amenity',inputMethod:'independent-authoring'});
                await s.placeAssets([
                    {...common,assetId:consoleAsset.assetId,assetDefinitionRevision:consoleAsset.assetDefinitionRevision,
                     position:{x,y:0,z:wallFace-.11-consoleAsset.definition.geometry.aabb.maximum.z},metadata:metadata('Lounge TV Console')},
                    {...common,assetId:tv.assetId,assetDefinitionRevision:tv.assetDefinitionRevision,
                     position:{x,y:1.05,z:wallFace-gap-tv.definition.geometry.aabb.maximum.z},metadata:metadata('Lounge TV'),
                     snapRelationship:{family:'wall_attachment',supportPlacementId:wall.placementId,
                       supportAssetDefinitionRevision:wall.assetDefinitionRevision,face:'negative_z',
                       localX:x-wall.transform.position.x,localY:1.05,normalGapMeters:gap}}
                ]);
                for(const [label,color] of [['Lounge TV Console','#35393E'],['Lounge TV','#17191C']]){
                    const p=s.getState().layout.placements.find(v=>v.metadata.instanceLabel===label);
                    s.select(p.placementId);await s.setSelectedAppearance(color);
                }
                s.clearSelection();return s.getState().layout;
            }''')
            added = audit(state['layout'], result)
            assert TARGET.read_bytes() == raw, 'Preview unexpectedly saved'
            write('draft.json', result)
            write('placement-check.json', dict(status='draft', placements=added, existingLayoutUnchanged=True))
        else:
            original = (OUT / 'layout-before.json').read_bytes()
            draft = json.loads((OUT / 'draft.json').read_text())
            review = json.loads((OUT / 'desktop-visual-review.json').read_text())
            assert review['status'] == 'passed'
            assert review['draftSha256'] == hashlib.sha256((OUT / 'draft.json').read_bytes()).hexdigest()
            if raw == original:
                assert state['layout'] == draft, 'Draft changed since review'
                page.evaluate(APP + '.session.save()')
                page.wait_for_function('!'+APP+'.session.getState().dirty', timeout=30000)
            else:
                # A completed Save may precede an interrupted verification step.
                assert not state['dirty'] and state['layout'] == json.loads(raw)
                actual, expected = deepcopy(state['layout']), deepcopy(draft)
                actual.pop('updatedAt'); expected.pop('updatedAt')
                assert actual == expected, 'Saved layout differs from the reviewed draft'
            saved = page.evaluate(APP + '.session.getState().layout')
            audit(json.loads(original), saved)
            assert json.loads(TARGET.read_bytes()) == saved
            hashes = json.loads((OUT / 'layout-hashes.json').read_text())
            assert all(hashlib.sha256((TARGET.parent / name).read_bytes()).hexdigest() == digest
                       for name, digest in hashes.items() if name not in (TARGET.name, 'registry.json'))
            write('saved.json', saved)
            write('save-check.json', dict(status='saved', otherLayoutsUnchanged=True, desktopMatchesSaved=True,
                                         updatedAt=saved['updatedAt']))
        page.evaluate(APP + ".workspace._setViewMode('3d')")
        page.evaluate(APP + ".workspace.threeAdapter.exitWalkthrough('lounge-tv-review')")
        page.wait_for_function(APP + '.workspace.threeAdapter.getDiagnostics().pendingLoads===0', timeout=120000)
        page.evaluate('''()=>{const a=window._trainFacilityLayoutAuthoringApp.workspace.threeAdapter,v=a.getCameraView();
            Object.assign(v,{position:{x:7.6,y:2.8,z:-9.6},target:{x:3.4,y:.85,z:-4.3},up:{x:0,y:1,z:0},fov:60,near:.05,far:250});a.applyCameraView(v)}''')
        page.wait_for_timeout(800)
        page.screenshot(path=str(OUT / ('lounge-tv-' + args.phase + '.png')), timeout=20000)
        diagnostic = page.evaluate(APP + '.workspace.threeAdapter.getDiagnostics()')
        group = next(g for g in diagnostic['representationGroups'] if g['assetId'] == 'asset-gym-lounge-tv-unit')
        assert group['representation'] in ('overview', 'detail') and group['prototypeMeshCount'] > 0
        assert not diagnostic['warnings'], diagnostic['warnings']
        write('desktop-render-check.json', dict(status='passed', phase=args.phase, console=group, warnings=diagnostic['warnings']))
        print(json.dumps(dict(status=args.phase, consoleLoaded=True, warnings=diagnostic['warnings'])))


if __name__ == '__main__':
    main()
