"""Inspect the complete STL TV set in staging and in the normal desktop app."""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from playwright.sync_api import sync_playwright
from tools import verify_private_gym_social_seating as render
from tools.replace_private_gym_tv_set import OUT, ASSET, NEW, OLD, audit
from tools.build_private_gym import STORE, LAYOUT, write

render.OUT=OUT
render.ASSETS=[ASSET]
render.LIVING=ASSET
render.SHOTS=[('gaming',(8,3.8,-10),(3.15,1,-4.5)),
              ('unit',(3.15,2.2,-10),(3.15,1,-3.4))]


def desktop():
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=target.read_bytes();saved=json.loads(raw)
    app='window._trainFacilityLayoutAuthoringApp'
    report=dict(status='running',captures=[])
    with sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        startup=browser.new_browser_cdp_session()
        deadline=time.monotonic()+120;page=None
        while page is None and time.monotonic()<deadline:
            # Pump protocol events while Electron creates its first window.
            # time.sleep alone leaves Playwright's cached page list stale.
            startup.send('Target.getTargets')
            page=next((p for c in browser.contexts for p in c.pages if p.url.startswith('http://127.0.0.1:8480/')),None)
            if page is None:time.sleep(.5)
        startup.detach()
        assert page is not None
        page.wait_for_function(app+'?.session?.getState().loaded',timeout=120000)
        state=page.evaluate(app+'.session.getState()')
        assert not state['dirty'] and state['layout']==saved
        catalog={a['assetId']:a for a in page.evaluate(app+'.workspace.assetCatalog.map(a=>a.source)')}
        report['checks']=audit(json.loads((OUT/'before.json').read_bytes()),saved,catalog)
        page.keyboard.press('Escape')
        page.evaluate(app+".workspace._setViewMode('3d')")
        adapter=app+'.workspace.threeAdapter'
        page.evaluate(adapter+".exitWalkthrough('correct-tv-review')")
        page.wait_for_function('id=>'+adapter+'.getDiagnostics().representationGroups.some(g=>g.assetId===id)',arg=ASSET,timeout=120000)
        render.captures(page,adapter,'desktop',report)
        d=page.evaluate(adapter+'.getDiagnostics()')
        group=next(g for g in d['representationGroups'] if g['assetId']==ASSET)
        assert group['placementIds']==[NEW]
        assert group['representation'] in ('overview','detail')
        assert group['assetDefinitionRevision']==catalog[ASSET]['assetDefinitionRevision']
        assert all(not OLD.intersection(g['placementIds']) for g in d['representationGroups'])
        url=catalog[ASSET]['overview']['path']
        served=page.evaluate('async u=>{let r=await fetch(u);if(!r.ok)throw Error(r.status);return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await r.arrayBuffer())),v=>v.toString(16).padStart(2,"0")).join("")}',url)
        assert served==hashlib.sha256((ROOT/url.lstrip('/')).read_bytes()).hexdigest()
        final=page.evaluate(app+'.session.getState()')
        assert final['layout']==saved and not final['dirty'] and final['selection']==state['selection']
        assert target.read_bytes()==raw
        report.update(status='passed',group=group,servedAssetHash=served,savedBytesUnchanged=True)
        write(OUT/'desktop-check.json',report)
        print(json.dumps(dict(status='passed',captures=len(report['captures']),saved=True)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--desktop',action='store_true')
    args=parser.parse_args()
    desktop() if args.desktop else render.staged()
