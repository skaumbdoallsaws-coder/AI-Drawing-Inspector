"""Render and verify the revised soccer-room finish without changing saved geometry."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from tools import verify_private_gym_kitchen_soccer as render
from tools.style_private_gym_soccer_room import OUT, SPECS, FACES, COLOR, audit, sha, STORE, LAYOUT, write

render.OUT=OUT
render.SHOTS=[('room',(36,15,41),(19,2,50)),
              ('soccer-speed-discipline',(14.55,3.4,54),(14.55,3.1,34.275)),
              ('soccer-train-champion',(12,3.5,48),(.275,3.1,48)),
              ('soccer-play-belong',(29,3.5,48),(41.725,3.1,48))]


def check(d,sources):
    assert not d['warnings'],d['warnings']
    assert d['placementTransformAudit']['transformMismatchCount']==0
    sources={s['artworkId']:s for s in sources}
    result=[]
    for spec in SPECS:
        a=next(a for a in d['exteriorArtwork'] if a['artworkId']==spec['id'])
        assert a['status']=='ready' and a['target']==dict(placementId=spec['wall'],face=spec['face'])
        frame=a['imageFrame'];box=sources[spec['id']]['alphaBounds']
        w=a['worldWidth']*frame['width'];h=a['worldHeight']*frame['height']
        assert abs(w/h-(box[2]-box[0])/(box[3]-box[1]))<1e-5
        assert abs(a['worldPosition']['y']-3.1)<1e-6
        if 'goal' in spec:
            assert abs(a['worldPosition']['z']-48)<1e-6
            assert abs(h-5.952)<1e-6
        else:
            assert w>27.8 and h>5.9
            assert abs(a['worldPosition']['x']-14.55)<1e-6
        result.append(dict(artworkId=spec['id'],width=w,height=h,center=a['worldPosition']))
    return result


render.check_diagnostics=check


def desktop():
    app='window._trainFacilityLayoutAuthoringApp'
    path=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    raw=path.read_bytes();saved=json.loads(raw)
    report=json.loads((OUT/'report.json').read_bytes())
    before=json.loads((OUT/'before.json').read_bytes())
    with render.sync_playwright() as pw:
        browser=pw.chromium.connect_over_cdp('http://127.0.0.1:9542',timeout=20000)
        page=next(p for c in browser.contexts for p in c.pages if p.url.startswith('http://127.0.0.1:8480/'))
        state=page.evaluate(app+'.session.getState()')
        assert not state['dirty'] and state['layout']==saved
        audit(before,saved,report['replacement'])
        page.evaluate(app+".workspace._setViewMode('3d')")
        adapter=app+'.workspace.threeAdapter'
        page.evaluate(adapter+".exitWalkthrough('soccer-finish-review')")
        render.ready(page,adapter)
        result=dict(status='running',frames=check(page.evaluate(adapter+'.getDiagnostics()'),report['sources']),captures=[])
        for name,p,t in render.SHOTS:
            render.camera(page,adapter,p,t)
            page.screenshot(path=str(OUT/f'desktop-{name}.png'),timeout=20000)
            result['captures'].append(name)
        for source in report['sources']:
            served=page.evaluate('async u=>{const r=await fetch(u);if(!r.ok)throw Error(r.status);return Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",await r.arrayBuffer())),v=>v.toString(16).padStart(2,"0")).join("")}', '/'+source['artifact'])
            assert served==source['sha256']
        render.camera(page,adapter,render.SHOTS[0][1],render.SHOTS[0][2])
        final=page.evaluate(app+'.session.getState()')
        assert final['layout']==saved and not final['dirty'] and path.read_bytes()==raw
        result.update(status='passed',savedBytesUnchanged=True,servedArtworkHashesVerified=True)
        write(OUT/'desktop-check.json',result)
        print(json.dumps(dict(status='passed',captures=len(result['captures']))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--desktop',action='store_true')
    desktop() if parser.parse_args().desktop else render.staged()
