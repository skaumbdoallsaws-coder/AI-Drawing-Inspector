"""Place and verify the two office bookshelf concepts through the desktop editor."""
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

OUT = ROOT / '.runtime/private-gym-bookshelves-20261010'
TARGET = ROOT / '.runtime/facility-layout/layouts/local/site-local/layouts/fl-private-gym-20261007.json'
APP = 'window._trainFacilityLayoutAuthoringApp'
LABELS = {'Office Floor Bookshelf with Books', 'Office Wall Bookshelf with Books'}


def write(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2), encoding='utf-8')


def audit(before, after):
    old = {p['placementId']: p for p in before['placements']}
    current = {p['placementId']: p for p in after['placements']}
    assert all(current.get(k) == v for k, v in old.items()), 'Existing office or gym object changed'
    added = [p for k, p in current.items() if k not in old]
    assert len(added) == 2 and {p['metadata']['instanceLabel'] for p in added} == LABELS
    assert all(p['transform']['scale'] == 1 for p in added)
    left, right = deepcopy(before), deepcopy(after)
    for value in (left, right):
        value.pop('placements'); value.pop('updatedAt')
    assert left == right, 'Geometry, artwork or other document content changed'
    return added


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['draft', 'review', 'save'])
    args = parser.parse_args()
    with sync_playwright() as pw:
        browser = pw.chromium.connect_over_cdp('http://127.0.0.1:9542', timeout=20000)
        page = next(v for c in browser.contexts for v in c.pages if v.url.startswith('http://127.0.0.1:8480/'))
        page.wait_for_function(APP + '?.session?.getState().loaded', timeout=120000)
        state = page.evaluate(APP + '.session.getState()')
        assert state['layout']['layoutId'] == 'fl-private-gym-20261007'
        raw = TARGET.read_bytes()
        if args.phase == 'draft':
            assert not state['dirty'] and state['layout'] == json.loads(raw), 'Unsaved user changes exist'
            assert not any(p['metadata'].get('instanceLabel') in LABELS for p in state['layout']['placements'])
            backup = OUT / 'layout-before.json'
            if backup.exists():
                assert backup.read_bytes() == raw, 'Saved base changed'
            else:
                backup.write_bytes(raw)
            write('layout-hashes.json', {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in TARGET.parent.glob('*.json')})
            draft = page.evaluate('''async()=>{
                const a=window._trainFacilityLayoutAuthoringApp,s=a.session,layout=s.getState().layout;
                const catalog=new Map(a.workspace.assetCatalog.map(v=>[v.assetId,v.source]));
                const floor=catalog.get('asset-gym-office-bookshelf-floor-books');
                const mounted=catalog.get('asset-gym-office-bookshelf-wall-books');
                const west=layout.placements.find(p=>p.placementId==='pl-gym-wellness-meeting-work-divider');
                const north=layout.placements.find(p=>p.placementId==='pl-gym-wellness-work-north-right');
                for(const wall of [west,north]){
                    const q=wall.transform.quaternion;
                    if(q.x||q.y||q.z||q.w!==1||wall.transform.scale!==1)throw Error('Wall orientation changed');
                }
                const wb=catalog.get(west.assetId).definition.geometry.aabb;
                const nb=catalog.get(north.assetId).definition.geometry.aabb;
                const fd=floor.definition.geometry.aabb,md=mounted.definition.geometry.aabb;
                const x=west.transform.position.x+wb.maximum.x+.04+fd.maximum.z;
                if(x+fd.maximum.z>=30.5)throw Error('Floor shelf intrudes into office access path');
                if(md.maximum.x-md.minimum.x>nb.maximum.x-nb.minimum.x-.1)throw Error('Wall shelf too wide');
                const meta=label=>({instanceLabel:label,room:'work',gymRole:'amenity',inputMethod:'independent-authoring',scaleEvidence:'Unitless STL; provisional centimetre interpretation'});
                await s.placeAssets([
                    {assetId:floor.assetId,assetDefinitionRevision:floor.assetDefinitionRevision,
                     position:{x,y:0,z:-4.8},quaternion:{x:0,y:Math.SQRT1_2,z:0,w:Math.SQRT1_2},scale:1,
                     metadata:meta('Office Floor Bookshelf with Books')},
                    {assetId:mounted.assetId,assetDefinitionRevision:mounted.assetDefinitionRevision,
                     position:{x:north.transform.position.x,y:1.15,z:north.transform.position.z+nb.minimum.z-.02-md.maximum.z},
                     quaternion:{x:0,y:1,z:0,w:0},scale:1,metadata:meta('Office Wall Bookshelf with Books'),
                     snapRelationship:{family:'wall_attachment',supportPlacementId:north.placementId,
                       supportAssetDefinitionRevision:north.assetDefinitionRevision,face:'negative_z',localX:0,localY:1.15,normalGapMeters:.02}}
                ]);s.clearSelection();return s.getState().layout;
            }''')
            added = audit(json.loads(raw), draft)
            assert TARGET.read_bytes() == raw, 'Draft unexpectedly saved'
            write('draft.json', draft)
            write('placement-check.json', dict(status='draft', placements=added, existingLayoutUnchanged=True))
        elif args.phase == 'save':
            before = (OUT / 'layout-before.json').read_bytes()
            draft = json.loads((OUT / 'draft.json').read_text())
            proof = json.loads((OUT / 'desktop-visual-review.json').read_text())
            assert proof['status'] == 'passed' and proof['draftSha256'] == hashlib.sha256((OUT / 'draft.json').read_bytes()).hexdigest()
            if raw == before:
                assert state['layout'] == draft, 'Draft changed since review'
                page.evaluate(APP + '.session.save()')
                page.wait_for_function('!' + APP + '.session.getState().dirty', timeout=30000)
            else:
                assert not state['dirty'] and state['layout'] == json.loads(raw)
                actual, expected = deepcopy(state['layout']), deepcopy(draft)
                actual.pop('updatedAt'); expected.pop('updatedAt')
                assert actual == expected, 'Saved layout differs from the reviewed draft'
            saved = page.evaluate(APP + '.session.getState().layout')
            audit(json.loads(before), saved)
            assert json.loads(TARGET.read_bytes()) == saved
            hashes = json.loads((OUT / 'layout-hashes.json').read_text())
            assert all(hashlib.sha256((TARGET.parent / n).read_bytes()).hexdigest() == h
                       for n, h in hashes.items() if n not in (TARGET.name, 'registry.json'))
            write('saved.json', saved)
            write('save-check.json', dict(status='saved', otherLayoutsUnchanged=True, desktopMatchesSaved=True, updatedAt=saved['updatedAt']))
        else:
            assert raw == (OUT / 'layout-before.json').read_bytes()
            assert state['layout'] == json.loads((OUT / 'draft.json').read_text()), 'Draft changed since placement'
        page.evaluate(APP + ".workspace._setViewMode('3d')")
        page.evaluate(APP + ".workspace.threeAdapter.exitWalkthrough('bookshelf-review')")
        page.wait_for_function(APP + '.workspace.threeAdapter.getDiagnostics().pendingLoads===0', timeout=120000)
        for name, position, target in [('office', (35, 3, -9.7), (32.8, 1, -4.5)),
                                       ('floor', (32.1, 1.1, -5.5), (30.25, .3, -4.8)),
                                       ('wall', (34.777, 1.65, -5.3), (34.777, 1.42, -3.2)),
                                       ('office-loaded', (35, 3, -9.7), (32.8, 1, -4.5))]:
            page.evaluate('([position,target])=>{const a=' + APP + '.workspace.threeAdapter,v=a.getCameraView();Object.assign(v,{position,target,up:{x:0,y:1,z:0},fov:60,near:.05,far:250});a.applyCameraView(v)}',
                          [dict(zip('xyz', position)), dict(zip('xyz', target))])
            page.wait_for_timeout(500)
            if name in ('floor', 'wall'):
                # Large layouts defer heavy models until the camera approaches them.
                page.wait_for_function('id=>' + APP + '.workspace.threeAdapter.getDiagnostics().representationGroups.some(g=>g.assetId===id&&["overview","detail"].includes(g.representation))',
                                       arg='asset-gym-office-bookshelf-' + name + '-books', timeout=120000)
                page.wait_for_timeout(300)
            page.screenshot(path=str(OUT / (name + '-' + args.phase + '.png')), timeout=20000)
        diagnostics = page.evaluate(APP + '.workspace.threeAdapter.getDiagnostics()')
        groups = [g for g in diagnostics['representationGroups'] if g['assetId'] in {
            'asset-gym-office-bookshelf-floor-books', 'asset-gym-office-bookshelf-wall-books'}]
        assert len(groups) == 2 and all(g['representation'] in ('overview', 'detail') for g in groups)
        assert not diagnostics['warnings'], diagnostics['warnings']
        write('desktop-render-check.json', dict(status='passed', phase=args.phase, groups=groups, warnings=[]))
        print(json.dumps(dict(status=args.phase, shelvesLoaded=len(groups), warnings=[])))


if __name__ == '__main__':
    main()
