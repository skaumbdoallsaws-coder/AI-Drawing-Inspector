"""Stage, verify and save four approved NKJV wall excerpts in Private Gym."""
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
from PIL import Image, ImageChops, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import STORE, LAYOUT, saved_hashes
from tools.preview_private_gym_scripture import HTML

OUT = ROOT/'.runtime/private-gym-scripture-20261011'
APPROVED = ROOT/'.runtime/private-gym-scripture-preview-20261011'
TARGET = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
FONT = Path('C:/Windows/Fonts/bahnschrift.ttf')
PREFIX = 'apex-scripture-'
SPECS = [
    dict(key='entrance', reference='Joshua 1:9', excerpt='Be strong and of good courage'),
    dict(key='strength', reference='Proverbs 24:5', excerpt='A wise man is strong',
         rows=[('A WISE MAN', 224, 170), ('IS STRONG', 148, 453), ('PROVERBS 24:5  |  NKJV', 66, 740)]),
    dict(key='cardio', reference='Hebrews 12:1', excerpt='let us run with endurance',
         rows=[('LET US RUN', 224, 170), ('WITH ENDURANCE', 148, 453), ('HEBREWS 12:1  |  NKJV', 66, 740)]),
    dict(key='hallway', reference='Ephesians 6:11', excerpt='Put on the whole armor of God',
         rows=[('PUT ON THE', 148, 100), ('WHOLE ARMOR', 224, 330),
               ('OF GOD', 148, 625), ('EPHESIANS 6:11  |  NKJV', 66, 890)]),
]
SHOTS = {
    'entrance': ((6.9, 1.7, 3.8), (.104, 2.25, 3.05), 64),
    'strength': ((5.8, 1.7, 23), (.104, 2.3, 23), 58),
    'cardio': ((28, 1.85, 4.65), (28, 2.65, .104), 67),
    'hallway': ((34.777, 1.7, -.32), (34.777, 1.95, -2.902), 60),
}


def write(name, data):
    (OUT/name).write_text(json.dumps(data, indent=2)+'\n', encoding='utf-8')


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def prepare_image(spec):
    if spec['key'] == 'entrance':
        return (APPROVED/'entrance-lettering.png').read_bytes()
    mask = Image.new('L', (2400, 1100))
    draw = ImageDraw.Draw(mask)
    assert ' '.join(row[0] for row in spec['rows'][:-1]) == spec['excerpt'].upper()
    for text, size, y in spec['rows']:
        font = ImageFont.truetype(str(FONT), size)
        box = draw.textbbox((0, 0), text, font=font)
        assert box[2]-box[0] < 2250
        draw.text(((2400-(box[2]-box[0]))/2-box[0], y-box[1]), text, font=font, fill=255)
    image = Image.new('RGB', mask.size, (201, 155, 57))
    painter = ImageDraw.Draw(image)
    for y in range(mask.height):
        weight = .13*max(0, 1-abs((y % 283)/283-.42)/.18)
        color = tuple(round(v+(255-v)*weight) for v in (201, 155, 57))
        painter.line((0, y, mask.width, y), fill=color)
    image.putalpha(mask)
    box = mask.getbbox()
    image = image.crop((box[0]-18, box[1]-18, box[2]+18, box[3]+18))
    assert image.getchannel('A').getextrema() == (0, 255)
    output = BytesIO()
    image.save(output, format='PNG')
    return output.getvalue()


def plan(before, sources, catalog):
    settings = before['extensions']['facilityPerimeterWalls']['settings']
    assert settings['boundary'] == [dict(x=0, z=0), dict(x=60, z=0), dict(x=60, z=30), dict(x=0, z=30)]
    assert settings['heightMeters'] == 3.6
    approved = json.loads((APPROVED/'report.json').read_bytes())['artwork']
    records = []
    for source in sources:
        key = source['key']
        record = dict(artworkId=PREFIX+key, imagePath='/'+source['artifact'], coverage=1, uv=[0, 0, 1, 1])
        if key == 'entrance':
            record.update({k:deepcopy(approved[k]) for k in ('target', 'region', 'coverage', 'uv')})
        elif key == 'strength':
            record.update(target=dict(edge=3, side='interior'), region=[5.7/30, 1.42/3.6, 8.3/30, 3.25/3.6])
        elif key == 'cardio':
            record.update(target=dict(edge=0, side='interior'), region=[25.7/60, 1.95/3.6, 30.3/60, 3.4/3.6])
        else:
            pid = 'pl-gym-wellness-work-north-right'
            p = next(p for p in before['placements'] if p['placementId'] == pid)
            bounds = catalog[(p['assetId'], p['assetDefinitionRevision'])]['definition']['geometry']['aabb']
            assert p['transform']['quaternion'] == dict(x=0, y=0, z=0, w=1)
            assert p['transform']['scale'] == 1 and p['transform']['position']['z'] == -3
            assert abs(bounds['maximum']['x']-bounds['minimum']['x']-1.942) < 1e-5
            record.update(target=dict(placementId=pid, face='positive_z'), region=[.08, .32, .92, .90])
        records.append(record)
    finish = settings['exteriorFinish']
    for record in records:
        region, target = record['region'], record['target']
        assert all(0 <= n <= 1 for n in region) and region[0] < region[2] and region[1] < region[3]
        if 'edge' in target:
            edge = target['edge']
            length = 60 if edge in (0, 2) else 30
            start, end = region[0]*length, region[2]*length
            for opening in settings['openings']:
                if opening['edge'] == edge:
                    assert end <= opening['startMeters'] or start >= opening['endMeters']
            for art in finish['artworks']:
                if art['edge'] == edge and art.get('side') == 'interior':
                    assert end <= art['startMeters'] or start >= art['startMeters']+art['widthMeters'], (record['artworkId'], art['artworkId'])
        for existing in finish['fittedArtworks']:
            assert existing['artworkId'] != record['artworkId']
            if existing['target'] == target:
                r = existing['region']
                assert region[2] <= r[0] or region[0] >= r[2] or region[3] <= r[1] or region[1] >= r[3]
    return records


def audit(before, after, records):
    expected = deepcopy(before)
    expected['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'].extend(records)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Changes beyond four new artwork records'
    return dict(artworksAdded=4, placementsUnchanged=len(before['placements']), geometryUnchanged=True,
                existingArtworkUnchanged=True, floorsUnchanged=True)


def stage():
    OUT.mkdir(parents=True, exist_ok=True)
    before_raw, library_raw = TARGET.read_bytes(), (ROOT/PRIVATE_ASSET_MANIFEST).read_bytes()
    assert before_raw == (APPROVED/'before.json').read_bytes(), 'Approved entrance base changed'
    for name, payload in [('before.json', before_raw), ('catalog-before.json', library_raw)]:
        path = OUT/name
        if path.exists():
            assert path.read_bytes() == payload, 'Staging base changed'
        else:
            path.write_bytes(payload)
    before = json.loads(before_raw)
    sources = []
    for spec in SPECS:
        raw = prepare_image(spec)
        artifact = 'generated/facility-wall-art/'+sha256(raw).hexdigest()+'.png'
        dest = ROOT/artifact
        if dest.exists():
            assert dest.read_bytes() == raw
        else:
            RevisionedAuthorityRepository._atomic_write(dest, raw)
        source = {k:spec[k] for k in ('key', 'reference', 'excerpt')}
        source.update(artifact=artifact, sha256=sha256(raw).hexdigest(), translation='NKJV',
                      source='https://www.biblegateway.com/passage/?search='+spec['reference'].replace(' ', '%20').replace(':', '%3A')+'&version=NKJV')
        sources.append(source)
    store = OUT/'validation-store'
    for folder in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(store/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(store, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = {(a['assetId'], a['assetDefinitionRevision']): a for a in host.authoritative_asset_catalog()}
        records = plan(before, sources, catalog)
        settings = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
        settings['exteriorFinish']['fittedArtworks'].extend(records)
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
    report = dict(status='validated', baseRevision=layout_revision(before), candidateSha256=digest(OUT/'candidate.json'),
                  records=records, sources=sources, checks=checks, layoutHashes=saved_hashes(),
                  userApprovedEntrance=True, usage='User-confirmed private gym, not public',
                  scriptureCopyright=dict(owner='Thomas Nelson', year=1982),
                  permissionsReview='https://www.biblegateway.com/versions/New-King-James-Version-NKJV-Bible/',
                  metallicAppearance='Gold-finish PNG highlights; unchanged existing unlit wall-art renderer')
    write('report.json', report)
    library = {a['assetId']:a for a in json.loads(library_raw)['assets']}
    fixtures = {}
    for key in SHOTS:
        fixture = deepcopy(candidate)
        def included(p):
            x, z = p['transform']['position']['x'], p['transform']['position']['z']
            if key == 'entrance':
                return 0 <= x <= 12 and 0 <= z <= 12
            if key == 'strength':
                return 0 <= x <= 17 and 12 <= z <= 30
            if key == 'cardio':
                return 12 <= x <= 36 and 0 <= z <= 12
            return 'north' in p['placementId'] and -3.5 <= z <= -.2 or p['placementId'] == 'pl-gym-wellness-corridor-west'
        fixture['placements'] = [p for p in candidate['placements'] if included(p)]
        ids = {p['placementId'] for p in fixture['placements']}
        finish = fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
        finish['fittedArtworks'] = [a for a in finish['fittedArtworks'] if 'edge' in a['target'] or a['target'].get('placementId') in ids]
        finish['wallFaces'] = [a for a in finish['wallFaces'] if a['placementId'] in ids]
        keys = {(p['assetId'], p['assetDefinitionRevision']) for p in fixture['placements']}
        fixtures[key] = dict(layout=fixture, catalog=[catalog[k] for k in sorted(keys)],
                             artifacts={a:dict(url='/'+library[a]['artifact'], sourceToCanonical=library[a]['sourceToCanonical']) for a, _ in keys})
    write('render-fixtures.json', fixtures)
    print(json.dumps(checks), flush=True)


def camera(page, expression, p, t, fov):
    page.evaluate('''([expr,p,t,fov])=>{const a=eval(expr),v=a.getCameraView();Object.assign(v,
      {position:p,target:t,up:{x:0,y:1,z:0},fov,near:.025,far:300});a.applyCameraView(v)}''',
                  [expression, dict(zip('xyz', p)), dict(zip('xyz', t)), fov])


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
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            try:
                for key, (p, t, fov) in SHOTS.items():
                    page = browser.new_page(viewport=dict(width=1600, height=1000))
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/preview/{key}')
                    page.wait_for_function('window.ready===true', timeout=120000)
                    for width, height in [(1600, 1000), (390, 700)]:
                        page.set_viewport_size(dict(width=width, height=height))
                        pos, angle = p, fov
                        if width < 500:
                            if key in ('entrance', 'strength'):
                                pos = (10, p[1], p[2])
                            elif key == 'cardio':
                                pos = (28, 1.85, 9.3)
                            angle = 90 if key == 'hallway' else 72
                        camera(page, 'adapter', pos, t, angle)
                        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0', timeout=120000)
                        camera(page, 'adapter', pos, t, angle)
                        page.wait_for_timeout(500)
                        d = page.evaluate('adapter.getDiagnostics()')
                        art = next(a for a in d['exteriorArtwork'] if a['artworkId'] == PREFIX+key)
                        assert art['status'] == 'ready' and not d['degraded']
                        assert d['placementTransformAudit']['transformMismatchCount'] == 0
                        png = page.screenshot(path=str(OUT/f'{width}-{key}.png'))
                        assert len(set(Image.open(BytesIO(png)).convert('RGB').getdata())) > 500
                        report['captures'].append(dict(key=key, viewport=[width, height], artwork=art))
                    page.set_viewport_size(dict(width=1600, height=1000))
                    camera(page, 'adapter', p, t, fov)
                    page.wait_for_timeout(500)
                    shown = page.screenshot()
                    page.evaluate('''async id=>{const l=structuredClone(fixture.layout);
                        l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks=
                        l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks.filter(a=>a.artworkId!==id);
                        await adapter.setScene({layout:l,assetCatalog:fixture.catalog})}''', PREFIX+key)
                    page.wait_for_function('adapter.getDiagnostics().pendingLoads===0', timeout=120000)
                    camera(page, 'adapter', p, t, fov)
                    page.wait_for_timeout(500)
                    hidden = page.screenshot(path=str(OUT/f'before-{key}.png'))
                    diff = ImageChops.difference(Image.open(BytesIO(shown)).convert('RGB'), Image.open(BytesIO(hidden)).convert('RGB'))
                    count = sum(max(pixel) > 25 for pixel in diff.getdata())
                    assert count > 1000, (key, 'Text not visible', count)
                    report.setdefault('visiblePixelChecks', {})[key] = count
                    page.evaluate('adapter.dispose()')
                    page.close()
                    print('Verified '+key, flush=True)
                assert not errors, errors
                report['status'] = 'passed'
            finally:
                browser.close()
    except Exception as exc:
        report.update(status='failed', error=str(exc), pageErrors=errors)
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        write('browser-check.json', report)
    print('All four wall graphics verified', flush=True)


def save():
    report = json.loads((OUT/'report.json').read_bytes())
    for name in ['browser-check.json', 'visual-review.json']:
        proof = json.loads((OUT/name).read_bytes())
        assert proof['status'] == 'passed' and proof['candidateSha256'] == digest(OUT/'candidate.json')
    assert TARGET.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed during review'
    assert (ROOT/PRIVATE_ASSET_MANIFEST).read_bytes() == (OUT/'catalog-before.json').read_bytes()
    for source in report['sources']:
        assert digest(ROOT/source['artifact']) == source['sha256']
    before, candidate = (json.loads((OUT/name).read_bytes()) for name in ('before.json', 'candidate.json'))
    audit(before, candidate, report['records'])
    host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
    try:
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
        audit(before, receipt['layout'], report['records'])
    finally:
        host.close()
    write('saved.json', receipt['layout'])
    assert json.loads(TARGET.read_bytes()) == receipt['layout']
    hashes = saved_hashes()
    assert all(hashes[k] == v for k, v in report['layoutHashes'].items() if k not in (TARGET.name, 'registry.json'))
    report.update(status='saved', savedRevision=receipt['revision'], otherLayoutsUnchanged=True)
    write('report.json', report)
    print('Saved four wall graphics; existing layout content unchanged', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'verify', 'save'])
    globals()[parser.parse_args().phase]()
