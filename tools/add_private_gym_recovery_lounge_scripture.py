"""Add two verified NKJV excerpts without changing the saved gym's other content."""
from copy import deepcopy
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from shutil import copytree
from threading import Thread
import argparse
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image, ImageChops
from playwright.sync_api import sync_playwright
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import STORE, LAYOUT, saved_hashes
from tools.add_private_gym_scripture import prepare_image, camera, digest
from tools.preview_private_gym_scripture import HTML

OUT = ROOT/'.runtime/private-gym-recovery-lounge-scripture-20261012'
TARGET = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
PREFIX = 'apex-scripture-'
SPECS = [
    dict(key='recovery', reference='Isaiah 40:29', excerpt='He gives power to the weak',
         rows=[('HE GIVES POWER', 224, 170), ('TO THE WEAK', 148, 453), ('ISAIAH 40:29  |  NKJV', 66, 740)],
         placementId='pl-8e028757b1982d3d17b9d714', face='negative_z',
         position=dict(x=55.8, y=0, z=9.6), size=(3, 3, .15),
         horizontal=(-1.32, 1.32), vertical=(1.5, 2.78)),
    dict(key='lounge', reference='Proverbs 27:17', excerpt='As iron sharpens iron',
         rows=[('AS IRON', 224, 170), ('SHARPENS IRON', 148, 453), ('PROVERBS 27:17  |  NKJV', 66, 740)],
         placementId='pl-gym-wellness-lounge-west', face='positive_x',
         position=dict(x=.12, y=0, z=-10.5), size=(.228, 3.2, 14.988),
         horizontal=(-3.75, 1.75), vertical=(1.35, 2.9)),
]
SHOTS = {
    'recovery': ((57.2, 1.7, 5.6), (55.8, 2.14, 9.511), 65),
    'lounge': ((8, 1.75, -10.6), (.248, 2.125, -11.5), 58),
}
MOBILE = {'recovery': ((55.8, 1.8, 4.8), 70), 'lounge': ((10.5, 1.75, -11.5), 80)}


def write(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def audit(before, after, records):
    expected = deepcopy(before)
    expected['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'].extend(records)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Change outside two new wall artwork records'
    return dict(artworksAdded=2, placementsUnchanged=len(before['placements']),
                existingArtAndScriptureUnchanged=True, geometryAndFloorsUnchanged=True)


def stage():
    OUT.mkdir(parents=True, exist_ok=True)
    before_raw, catalog_raw = TARGET.read_bytes(), (ROOT/PRIVATE_ASSET_MANIFEST).read_bytes()
    for name, raw in [('before.json', before_raw), ('catalog-before.json', catalog_raw)]:
        path = OUT/name
        if path.exists():
            assert path.read_bytes() == raw, 'Source changed since staging'
        else:
            path.write_bytes(raw)
    before = json.loads(before_raw)
    store = OUT/'validation-store'
    for folder in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(store/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
    records, sources, measured = [], [], []
    try:
        catalog = {(a['assetId'], a['assetDefinitionRevision']): a for a in host.authoritative_asset_catalog()}
        settings = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
        finish = settings['exteriorFinish']
        assert {PREFIX+k for k in ('entrance', 'strength', 'cardio', 'hallway')} <= {a['artworkId'] for a in finish['fittedArtworks']}
        for spec in SPECS:
            p = next(p for p in before['placements'] if p['placementId'] == spec['placementId'])
            assert p['transform'] == dict(position=spec['position'], quaternion=dict(x=0,y=0,z=0,w=1), scale=1)
            bounds = catalog[(p['assetId'], p['assetDefinitionRevision'])]['definition']['geometry']['aabb']
            lo, hi = bounds['minimum'], bounds['maximum']
            assert all(abs(hi[k]-lo[k]-v) < 1e-5 for k, v in zip('xyz', spec['size']))
            axis = 'x' if spec['face'].endswith('_z') else 'z'
            u = [(v-lo[axis])/(hi[axis]-lo[axis]) for v in spec['horizontal']]
            v = [(v-lo['y'])/(hi['y']-lo['y']) for v in spec['vertical']]
            region = [u[0],v[0],u[1],v[1]]
            assert all(0 <= n <= 1 for n in region) and u[0] < u[1] and v[0] < v[1]
            target = dict(placementId=p['placementId'], face=spec['face'])
            for a in finish['fittedArtworks']:
                assert a['artworkId'] != PREFIX+spec['key']
                if a['target'] == target:
                    r = a['region']
                    assert region[2] <= r[0] or region[0] >= r[2] or region[3] <= r[1] or region[1] >= r[3]
            raw = prepare_image(spec)
            rel = 'generated/facility-wall-art/'+sha256(raw).hexdigest()+'.png'
            dest = ROOT/rel
            if dest.exists():
                assert dest.read_bytes() == raw
            else:
                RevisionedAuthorityRepository._atomic_write(dest, raw)
            records.append(dict(artworkId=PREFIX+spec['key'], imagePath='/'+rel,
                                target=target, region=region, coverage=1, uv=[0,0,1,1]))
            sources.append(dict(key=spec['key'], reference=spec['reference'], excerpt=spec['excerpt'],
                                artifact=rel, sha256=sha256(raw).hexdigest(), translation='NKJV',
                                source='https://www.biblegateway.com/passage/?search='+spec['reference'].replace(' ', '%20').replace(':', '%3A')+'&version=NKJV'))
            measured.append(dict(placementId=p['placementId'], bounds=bounds, transform=p['transform'], region=region))
        finish['fittedArtworks'].extend(records)
        candidate = apply_facility_layout_operations(before, [dict(op='set_perimeter_walls', wallSettings=settings)])['document']
        audit(before, candidate, records)
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write('spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        candidate = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))['layout']
        checks = audit(before, candidate, records)
    finally:
        host.close()
    write('candidate.json', candidate)
    write('report.json', dict(status='validated', baseRevision=layout_revision(before),
          candidateSha256=digest(OUT/'candidate.json'), records=records, sources=sources, measuredWalls=measured,
          checks=checks, layoutHashes=saved_hashes(), usage='User-confirmed private gym, not public',
          scriptureCopyright=dict(owner='Thomas Nelson', year=1982),
          metallicAppearance='Approved gold-finish PNG shading, existing unlit wall-art renderer'))
    library = {a['assetId']:a for a in json.loads(catalog_raw)['assets']}
    fixtures = {}
    for key in SHOTS:
        fixture = deepcopy(candidate)
        def included(p):
            x,z = p['transform']['position']['x'],p['transform']['position']['z']
            return 50 <= x <= 60 and 0 <= z <= 11 if key == 'recovery' else 0 <= x <= 22 and -18 <= z <= 0
        fixture['placements'] = [p for p in candidate['placements'] if included(p)]
        ids = {p['placementId'] for p in fixture['placements']}
        finish = fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
        finish['fittedArtworks'] = [a for a in finish['fittedArtworks'] if 'edge' in a['target'] or a['target'].get('placementId') in ids]
        finish['wallFaces'] = [a for a in finish['wallFaces'] if a['placementId'] in ids]
        keys = {(p['assetId'],p['assetDefinitionRevision']) for p in fixture['placements']}
        fixtures[key] = dict(layout=fixture, catalog=[catalog[k] for k in sorted(keys)],
          artifacts={a:dict(url='/'+library[a]['artifact'], sourceToCanonical=library[a]['sourceToCanonical']) for a,_ in keys})
    write('render-fixtures.json', fixtures)
    print(json.dumps(checks), flush=True)


def verify():
    fixtures = json.loads((OUT/'render-fixtures.json').read_bytes())
    report = dict(status='running', candidateSha256=digest(OUT/'candidate.json'), captures=[])
    errors = []
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_GET(self):
            if self.path.startswith('/preview/'):
                key = self.path.removeprefix('/preview/')
                raw = HTML.replace("fetch('/fixture.json')", "fetch('/fixture/"+key+"')").encode()
                kind = 'text/html'
            elif self.path.startswith('/fixture/'):
                raw = json.dumps(fixtures[self.path.removeprefix('/fixture/')]).encode()
                kind = 'application/json'
            else:
                return super().do_GET()
            self.send_response(200)
            self.send_header('Content-Type', kind)
            self.send_header('Content-Length', str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
    server = ThreadingHTTPServer(('127.0.0.1',0), partial(Handler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            try:
                for key,(p,t,fov) in SHOTS.items():
                    page = browser.new_page(viewport=dict(width=1600,height=1000))
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/preview/{key}')
                    page.wait_for_function('window.ready===true',timeout=120000)
                    for width,height in [(1600,1000),(390,700)]:
                        page.set_viewport_size(dict(width=width,height=height))
                        pos,angle = MOBILE[key] if width < 500 else (p,fov)
                        camera(page,'adapter',pos,t,angle)
                        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0',timeout=120000)
                        camera(page,'adapter',pos,t,angle)
                        page.wait_for_timeout(700)
                        d = page.evaluate('adapter.getDiagnostics()')
                        art = next(a for a in d['exteriorArtwork'] if a['artworkId'] == PREFIX+key)
                        assert art['status'] == 'ready' and not d['degraded']
                        assert d['placementTransformAudit']['transformMismatchCount'] == 0
                        shown = page.screenshot(path=str(OUT/f'{width}-{key}.png'))
                        assert len(set(Image.open(BytesIO(shown)).convert('RGB').getdata())) > 500
                        page.evaluate('''async id=>{const l=structuredClone(fixture.layout);
                          l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks=
                          l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks.filter(a=>a.artworkId!==id);
                          await adapter.setScene({layout:l,assetCatalog:fixture.catalog})}''', PREFIX+key)
                        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0',timeout=120000)
                        camera(page,'adapter',pos,t,angle)
                        page.wait_for_timeout(500)
                        hidden = page.screenshot(path=str(OUT/f'{width}-{key}-before.png'))
                        diff = ImageChops.difference(Image.open(BytesIO(shown)).convert('RGB'),Image.open(BytesIO(hidden)).convert('RGB'))
                        count = sum(max(pixel)>25 for pixel in diff.getdata())
                        assert count > 400, (key,width,'Lettering not visible',count)
                        report['captures'].append(dict(key=key,viewport=[width,height],artwork=art,visibleChangedPixels=count))
                        page.evaluate('async()=>adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog})')
                    page.evaluate('adapter.dispose()')
                    page.close()
                    print('Verified '+key,flush=True)
                assert not errors,errors
                report['status'] = 'passed'
            finally:
                browser.close()
    except Exception as exc:
        report.update(status='failed',error=str(exc),pageErrors=errors)
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        write('browser-check.json',report)
    print('Both wall graphics verified',flush=True)


def save():
    report = json.loads((OUT/'report.json').read_bytes())
    for name in ['browser-check.json','visual-review.json']:
        proof = json.loads((OUT/name).read_bytes())
        assert proof['status'] == 'passed' and proof['candidateSha256'] == digest(OUT/'candidate.json')
    assert TARGET.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed during review'
    assert (ROOT/PRIVATE_ASSET_MANIFEST).read_bytes() == (OUT/'catalog-before.json').read_bytes()
    for source in report['sources']:
        assert digest(ROOT/source['artifact']) == source['sha256']
    before,candidate = (json.loads((OUT/name).read_bytes()) for name in ('before.json','candidate.json'))
    audit(before,candidate,report['records'])
    host = LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        receipt = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],report['records'])
    finally:
        host.close()
    write('saved.json',receipt['layout'])
    assert json.loads(TARGET.read_bytes()) == receipt['layout']
    hashes = saved_hashes()
    assert all(hashes[k] == v for k,v in report['layoutHashes'].items() if k not in (TARGET.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write('report.json',report)
    print('Saved recovery and lounge Scripture; all existing content unchanged',flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','verify','save'])
    globals()[parser.parse_args().phase]()
