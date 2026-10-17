"""Verify the saved office finish and shelf removal in the normal desktop app."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
os.environ['PW_TEST_SCREENSHOT_NO_FONTS_READY'] = '1'
from playwright.sync_api import sync_playwright
from PIL import Image
from tools.trim_private_gym_office_walls import OUT, TARGETS, FLOOR_SHELF, WALL_SHELF, audit
from tools.build_private_gym import STORE, LAYOUT

APP = 'window._trainFacilityLayoutAuthoringApp'


def main():
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=path.read_bytes()
    saved=json.loads(raw)
    report=json.loads((OUT/'report.json').read_bytes())
    audit(json.loads((OUT/'before.json').read_bytes()),saved,report['replacements'])
    assert not any(p['placementId']==FLOOR_SHELF for p in saved['placements'])
    assert any(p['placementId']==WALL_SHELF for p in saved['placements'])
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        deadline=time.monotonic()+120
        page=None
        while page is None and time.monotonic()<deadline:
            page=next((v for c in browser.contexts for v in c.pages if v.url.startswith('http://127.0.0.1:8480/')),None)
            if page is None:
                time.sleep(.5)
        assert page is not None, 'Normal desktop page did not open'
        page.wait_for_function(APP+'?.session?.getState().loaded',timeout=120000)
        state=page.evaluate(APP+'.session.getState()')
        assert state['layout']==saved and not state['dirty']
        page.evaluate(APP+".workspace._setViewMode('3d')")
        page.evaluate(APP+".workspace.threeAdapter.exitWalkthrough('office-finish-review')")
        page.wait_for_function(APP+'.workspace.threeAdapter.getDiagnostics().pendingLoads===0',timeout=120000)
        page.wait_for_timeout(600)
        captures=[]
        for name,position,target in [('wall-shelf',(34.777,1.65,-5.3),(34.777,1.42,-3.2)),
                ('office-door',(35,2.5,-9.7),(32.8,1.4,-3.2)),
                ('office-logo',(31.2,2,-4.9),(33,1.4,-10.8)),
                ('office-overview',(35,3,-9.7),(32.8,1,-4.5))]:
            page.evaluate('([position,target])=>{const a='+APP+'.workspace.threeAdapter,v=a.getCameraView();Object.assign(v,{position,target,up:{x:0,y:1,z:0},fov:65,near:.05,far:250});a.applyCameraView(v)}',
                [dict(zip('xyz',position)),dict(zip('xyz',target))])
            page.wait_for_function('ids=>ids.every(id=>'+APP+'.workspace.threeAdapter.getDiagnostics().representationGroups.some(g=>g.assetId===id&&["overview","detail"].includes(g.representation)))',
                arg=[v['assetId'] for v in report['replacements'].values()]+['asset-gym-office-bookshelf-wall-books'],timeout=120000)
            page.wait_for_timeout(400)
            screenshot=page.screenshot(path=str(OUT/(name+'-desktop.png')),timeout=20000)
            assert len(set(Image.open(io.BytesIO(screenshot)).convert('RGB').getdata()))>1000
            captures.append(dict(name=name,sha256=hashlib.sha256(screenshot).hexdigest()))
        diagnostic=page.evaluate(APP+'.workspace.threeAdapter.getDiagnostics()')
        assert not diagnostic['warnings'],diagnostic['warnings']
        groups={g['assetId']:g for g in diagnostic['representationGroups']}
        catalog=page.evaluate(APP+'.workspace.assetCatalog.map(a=>a.source)')
        assets=[]
        for pid,binding in report['replacements'].items():
            group=groups[binding['assetId']]
            assert group['assetDefinitionRevision']==binding['assetDefinitionRevision']
            asset=next(a for a in catalog if a['assetId']==binding['assetId'])
            url=asset['overview']['path']
            served=page.evaluate('async url=>{const r=await fetch(url);if(!r.ok)throw Error(r.status);const h=await crypto.subtle.digest("SHA-256",await r.arrayBuffer());return Array.from(new Uint8Array(h),v=>v.toString(16).padStart(2,"0")).join("")}',url)
            assert served==hashlib.sha256((ROOT/url.lstrip('/')).read_bytes()).hexdigest()
            assets.append(dict(placementId=pid,assetId=binding['assetId'],sha256=served))
        final=page.evaluate(APP+'.session.getState()')
        assert final['layout']==saved and not final['dirty'] and final['selection']==state['selection']
        assert path.read_bytes()==raw
        (OUT/'desktop-check.json').write_text(json.dumps(dict(status='passed',assets=assets,captures=captures,
            removedFloorShelf=True,wallShelfRetained=True,savedBytesUnchanged=True,warnings=[]),indent=2),encoding='utf8')
        print(json.dumps(dict(status='passed',walls=len(assets),captures=len(captures))))


if __name__=='__main__':
    main()
