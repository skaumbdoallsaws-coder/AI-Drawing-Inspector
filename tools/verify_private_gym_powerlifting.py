"""Render exact CAD placements on desktop/mobile before publishing the gym."""
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from threading import Thread
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
from tools.add_private_gym_powerlifting import OUT, A, P, sha, write
from tools.preview_private_gym_scripture import HTML
from tools.add_private_gym_scripture import camera

SHOTS = [
    ('rack','outdoor',(56,2.3,61.6),(52.7,.8,65.1),['rack']),
    ('bar','outdoor',(55.4,1.5,67.8),(52.7,.2,69.7),['bar']),
    ('outdoor-overview','outdoor',(61,13,76),(52.8,0,66),['bar','rack']),
    ('rear-delt','indoor',(46.8,2.1,25.9),(43.5,.9,24),['rear-delt']),
]


def main():
    fixtures = json.loads((OUT/'render-fixtures.json').read_bytes())
    candidate = json.loads((OUT/'candidate.json').read_bytes())
    for fixture in fixtures.values():
        assert all(p == next(a for a in candidate['placements'] if a['placementId']==p['placementId']) for p in fixture['layout']['placements'])
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_GET(self):
            if self.path.startswith('/preview/'):
                area = self.path.removeprefix('/preview/')
                data,kind = HTML.replace("fetch('/fixture.json')", "fetch('/fixture/"+area+"')").encode(),'text/html'
            elif self.path.startswith('/fixture/'):
                data,kind = json.dumps(fixtures[self.path.removeprefix('/fixture/')]).encode(),'application/json'
            else:
                return super().do_GET()
            self.send_response(200)
            self.send_header('Content-Type',kind)
            self.send_header('Content-Length',str(len(data)))
            self.end_headers()
            self.wfile.write(data)
    server = ThreadingHTTPServer(('127.0.0.1',0),partial(Handler,directory=str(ROOT)))
    thread = Thread(target=server.serve_forever,daemon=True)
    thread.start()
    report = dict(status='running',candidateSha256=sha(OUT/'candidate.json'),captures=[])
    errors = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True,args=['--enable-unsafe-swiftshader'])
            try:
                for area in fixtures:
                    page = browser.new_page(viewport=dict(width=1440,height=900))
                    page.on('pageerror',lambda e:errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/preview/{area}')
                    page.wait_for_function('window.ready===true',timeout=120000)
                    for name,room,pos,target,keys in SHOTS:
                        if room != area:
                            continue
                        ids = [A+k for k in keys]
                        for width,height in [(1440,900),(390,700)]:
                            page.set_viewport_size(dict(width=width,height=height))
                            fov = 80 if width<600 else 55
                            camera(page,'adapter',pos,target,fov)
                            page.wait_for_function('adapter.getDiagnostics().pendingLoads===0',timeout=180000)
                            camera(page,'adapter',pos,target,fov)
                            page.wait_for_timeout(700)
                            d = page.evaluate('adapter.getDiagnostics()')
                            assert not d['degraded'] and d['placementTransformAudit']['transformMismatchCount']==0
                            assert all(any(g['assetId']==aid and g['representation'] in ('overview','detail') for g in d['representationGroups']) for aid in ids)
                            assert not [w for w in d['warnings'] if w.get('assetId') in ids]
                            png = page.screenshot(path=str(OUT/f'{width}-{name}.png'),timeout=30000)
                            assert len(set(Image.open(BytesIO(png)).convert('RGB').getdata()))>500,'Blank scene'
                            record = dict(name=name,viewport=[width,height],transformMismatchCount=0,
                                          meshGroups=[g for g in d['representationGroups'] if g['assetId'] in ids])
                            if len(keys)==1:
                                page.evaluate('''async aid=>{const l=structuredClone(fixture.layout);
                                    l.placements=l.placements.filter(p=>p.assetId!==aid);
                                    await adapter.setScene({layout:l,assetCatalog:fixture.catalog})}''',ids[0])
                                page.wait_for_function('adapter.getDiagnostics().pendingLoads===0',timeout=180000)
                                camera(page,'adapter',pos,target,fov)
                                page.wait_for_timeout(500)
                                hidden = page.screenshot(timeout=30000)
                                diff = ImageChops.difference(Image.open(BytesIO(png)).convert('RGB'),Image.open(BytesIO(hidden)).convert('RGB'))
                                count = sum(max(p)>25 for p in diff.getdata())
                                assert count>250,('New object not visible',name,width,count)
                                record['newObjectVisiblePixels'] = count
                                page.evaluate('async()=>adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog})')
                            report['captures'].append(record)
                            print(f'Verified {width}-{name}',flush=True)
                    page.evaluate('adapter.dispose()')
                    page.close()
                assert not errors,errors
                report['status'] = 'passed'
            finally:
                browser.close()
    except Exception as error:
        report.update(status='failed',error=str(error),pageErrors=errors)
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        write(OUT/'browser-check.json',report)
    print(json.dumps(dict(status=report['status'],captures=len(report['captures']))),flush=True)


if __name__=='__main__':
    main()
