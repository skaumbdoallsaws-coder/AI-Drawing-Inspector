"""Render an entrance-only Scripture proposal without saving any gym changes."""
from copy import deepcopy
from functools import partial
from hashlib import sha256
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pathlib import Path
from threading import Thread
import json
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image, ImageChops, ImageDraw, ImageFont
from playwright.sync_api import sync_playwright
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

OUT = ROOT/'.runtime/private-gym-scripture-preview-20261011'
LAYOUT = ROOT/'.runtime/facility-layout/layouts/local/site-local/layouts/fl-private-gym-20261007.json'
ART_ID = 'preview-entrance-joshua-1-9'
EXCERPT = 'Be strong and of good courage'
GOLD = (201, 155, 57)


def write(name, value):
    (OUT/name).write_text(json.dumps(value, indent=2)+'\n', encoding='utf-8')


def lettering():
    mask = Image.new('L', (2400, 1000))
    draw = ImageDraw.Draw(mask)
    font = Path('C:/Windows/Fonts/bahnschrift.ttf')
    rows = [('BE STRONG', 224, 170), ('AND OF GOOD COURAGE', 148, 453),
            ('JOSHUA 1:9  |  NKJV', 66, 740)]
    assert ' '.join(row[0] for row in rows[:2]) == EXCERPT.upper()
    for text, size, y in rows:
        face = ImageFont.truetype(str(font), size)
        box = draw.textbbox((0, 0), text, font=face)
        assert box[2]-box[0] < 2250
        draw.text(((2400-(box[2]-box[0]))/2-box[0], y-box[1]), text, font=face, fill=255)
    # The PNG carries gold-finish shading, not a claim of a reflective PBR metal.
    color = Image.new('RGB', mask.size, GOLD)
    painter = ImageDraw.Draw(color)
    for y in range(mask.height):
        phase = (y % 283)/283
        weight = .13*max(0, 1-abs(phase-.42)/.18)
        rgb = tuple(round(v+(255-v)*weight) for v in GOLD)
        painter.line((0, y, mask.width, y), fill=rgb)
    color.putalpha(mask)
    bounds = mask.getbbox()
    color = color.crop((bounds[0]-18, bounds[1]-18, bounds[2]+18, bounds[3]+18))
    color.save(OUT/'entrance-lettering.png')
    assert color.getchannel('A').getextrema() == (0, 255)
    return dict(pixels=list(color.size), baseColor='#C99B39', font=font.name,
                excerpt=EXCERPT, reference='Joshua 1:9', translation='NKJV',
                punctuation='Contiguous excerpt, no terminal punctuation added',
                source='https://www.biblegateway.com/passage/?search=Joshua%201%3A9&version=NKJV',
                permissionStatus='Personal design preview; no public-display license asserted',
                permissionSource='https://www.biblegateway.com/versions/New-King-James-Version-NKJV-Bible/',
                copyrightOwner='Thomas Nelson', copyrightYear=1982)


def prepare():
    OUT.mkdir(parents=True, exist_ok=True)
    raw, catalog_raw = LAYOUT.read_bytes(), (ROOT/PRIVATE_ASSET_MANIFEST).read_bytes()
    before = json.loads(raw)
    assert before['layoutId'] == 'fl-private-gym-20261007'
    for name, payload in [('before.json', raw), ('catalog-before.json', catalog_raw)]:
        dest = OUT/name
        if dest.exists():
            assert dest.read_bytes() == payload, 'Source changed since this preview was prepared'
        else:
            dest.write_bytes(payload)
    source = lettering()
    candidate = deepcopy(before)
    settings = candidate['extensions']['facilityPerimeterWalls']['settings']
    finish = settings['exteriorFinish']
    a, b = settings['boundary'][3], settings['boundary'][0]
    assert a == dict(x=0, z=30) and b == dict(x=0, z=0)
    assert settings['heightMeters'] == 3.6
    # West reception wall: clear span before the lion at z=5.775..8.225.
    start, end, bottom, top = 24.70, 29.40, 1.42, 3.25
    for art in finish['artworks']:
        if art.get('side') == 'interior' and art['edge'] == 3:
            assert end <= art['startMeters'] or start >= art['startMeters']+art['widthMeters'], 'Existing artwork overlap'
    for opening in settings['openings']:
        if opening['edge'] == 3:
            assert end <= opening['startMeters'] or start >= opening['endMeters'], 'Opening overlap'
    record = dict(artworkId=ART_ID, imagePath='/entrance-lettering.png',
                  target=dict(edge=3, side='interior'),
                  region=[start/30, bottom/3.6, end/30, top/3.6],
                  coverage=1, uv=[0, 0, 1, 1])
    assert not any(a['artworkId'] == ART_ID for a in finish['fittedArtworks'])
    finish['fittedArtworks'].append(record)
    restored = deepcopy(candidate)
    restored['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'].pop()
    assert restored == before, 'Unexpected change outside entrance lettering'
    write('candidate.json', candidate)
    host = LocalFacilityLayoutHost(OUT/'catalog-store', private_assets=True, private_asset_root=ROOT)
    try:
        catalog = {(a['assetId'], a['assetDefinitionRevision']): a for a in host.authoritative_asset_catalog()}
    finally:
        host.close()
    library = {a['assetId']: a for a in json.loads(catalog_raw)['assets']}
    fixture = deepcopy(candidate)
    fixture['placements'] = [p for p in before['placements']
                             if -1 <= p['transform']['position']['x'] <= 38
                             and -3.5 <= p['transform']['position']['z'] <= 12]
    ids = {p['placementId'] for p in fixture['placements']}
    preview_finish = fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    preview_finish['fittedArtworks'] = [a for a in preview_finish['fittedArtworks']
                                     if 'edge' in a['target'] or a['target'].get('placementId') in ids]
    preview_finish['wallFaces'] = [a for a in preview_finish['wallFaces'] if a['placementId'] in ids]
    keys = {(p['assetId'], p['assetDefinitionRevision']) for p in fixture['placements']}
    assert all(key in catalog for key in keys), 'Unresolved placed asset revision'
    fixture = dict(layout=fixture, catalog=[catalog[k] for k in sorted(keys)],
                   artifacts={a:dict(url='/'+library[a]['artifact'], sourceToCanonical=library[a]['sourceToCanonical']) for a, _ in keys})
    write('render-fixture.json', fixture)
    report = dict(status='staged-preview-only', source=source, artwork=record,
                  savedLayoutSha256=sha256(raw).hexdigest(),
                  candidateSha256=sha256((OUT/'candidate.json').read_bytes()).hexdigest(),
                  wall=dict(edge=3, side='interior', x=0, zRange=[.60, 5.30],
                            usableHeightRange=[bottom, top], wallHeight=3.6),
                  scope='Actual reception CAD and surrounding assets rendered by the application adapter; no production save',
                  savedPlacements=len(before['placements']), previewPlacements=len(fixture['layout']['placements']))
    write('report.json', report)
    return fixture, report, raw, catalog_raw


HTML = '''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1">
<style>html,body,#scene{margin:0;width:100%;height:100%;overflow:hidden}</style>
<script type="importmap">{"imports":{"three":"/static/vendor/three/0.184.0/build/three.module.min.js"}}</script>
<script src="/static/facility_layout_avatar.js"></script>
<script src="/static/walkthrough_camera_settings.js"></script>
<script src="/static/facility_layout_walls.js"></script>
<script src="/static/facility_layout_three_adapter.js"></script></head><body><div id="scene"></div>
<script type="module">
import * as THREE from 'three';
import {OrbitControls} from '/static/vendor/three/0.184.0/examples/jsm/controls/OrbitControls.js';
import {GLTFLoader} from '/static/vendor/three/0.184.0/examples/jsm/loaders/GLTFLoader.js';
window.fixture=await(await fetch('/fixture.json')).json();
window.adapter=InspectorProFacilityThree.createThreeAdapter({THREE,OrbitControls,GLTFLoader,
 worldBounds:{minX:0,minZ:-18,maxX:82,maxZ:72,floorY:0},
 assetResolver:r=>r.stage==='overview'?fixture.artifacts[r.assetId]:null});
adapter.mount(document.getElementById('scene'));
await adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog});window.ready=true;
</script></body></html>'''


def render():
    fixture, report, raw, catalog_raw = prepare()

    class Handler(SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            payloads = {'/': (HTML.encode(), 'text/html'),
                        '/fixture.json': (json.dumps(fixture).encode(), 'application/json'),
                        '/entrance-lettering.png': ((OUT/'entrance-lettering.png').read_bytes(), 'image/png')}
            if self.path in payloads:
                body, kind = payloads[self.path]
                self.send_response(200)
                self.send_header('Content-Type', kind)
                self.send_header('Content-Length', str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            elif self.path.startswith(('/static/', '/generated/')):
                super().do_GET()
            else:
                self.send_error(404)

    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(ROOT)))
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    errors, shots = [], []

    def camera(page, p, t, fov):
        page.evaluate('''([p,t,fov])=>{const v=adapter.getCameraView();Object.assign(v,
          {position:p,target:t,up:{x:0,y:1,z:0},fov,near:.025,far:250});adapter.applyCameraView(v)}''',
                      [dict(zip('xyz', p)), dict(zip('xyz', t)), fov])

    def ready(page):
        page.wait_for_function('adapter.getDiagnostics().pendingLoads===0', timeout=120000)
        page.wait_for_timeout(500)

    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True, args=['--enable-unsafe-swiftshader'])
            try:
                for width, height in [(1600, 1000), (390, 700)]:
                    page = browser.new_page(viewport=dict(width=width, height=height), device_scale_factor=1)
                    page.on('pageerror', lambda e: errors.append(str(e)))
                    page.goto(f'http://127.0.0.1:{server.server_port}/')
                    page.wait_for_function('window.ready===true', timeout=120000)
                    views = [('entrance-preview', (6.9, 1.7, 3.8), (.104, 2.25, 3.05), 64),
                             ('entrance-context', (10.3, 2.4, 9.4), (2.8, 1.6, 2.4), 66),
                             ('entrance-front', (6.5, 2.25, 2.95), (.104, 2.25, 2.95), 52)]
                    if width < 500:
                        views = [('entrance-mobile', (10, 2.25, 2.95), (.104, 2.25, 2.95), 72)]
                    for name, p, t, fov in views:
                        camera(page, p, t, fov)
                        ready(page)
                        camera(page, p, t, fov)
                        page.wait_for_timeout(500)
                        d = page.evaluate('adapter.getDiagnostics()')
                        art = next(a for a in d['exteriorArtwork'] if a['artworkId'] == ART_ID)
                        assert art['status'] == 'ready', art
                        assert not d['degraded'] and d['placementTransformAudit']['transformMismatchCount'] == 0
                        png = page.screenshot(path=str(OUT/(name+'.png')))
                        pixels = list(Image.open(BytesIO(png)).convert('RGB').getdata())
                        assert len(set(pixels)) > 500, 'Blank viewport'
                        page.evaluate('''async id=>{const l=structuredClone(fixture.layout);
                          l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks=
                          l.extensions.facilityPerimeterWalls.settings.exteriorFinish.fittedArtworks.filter(a=>a.artworkId!==id);
                          await adapter.setScene({layout:l,assetCatalog:fixture.catalog});}''', ART_ID)
                        ready(page)
                        camera(page, p, t, fov)
                        page.wait_for_timeout(400)
                        baseline = page.screenshot(path=str(OUT/(name+'-before.png')))
                        diff = ImageChops.difference(Image.open(BytesIO(png)).convert('RGB'), Image.open(BytesIO(baseline)).convert('RGB'))
                        changed = sum(max(pixel) > 25 for pixel in diff.getdata())
                        assert changed > 500, ('Lettering not visible', name, changed)
                        shots.append(dict(name=name, changedPixels=changed, artwork=art, viewport=[width, height]))
                        page.evaluate('async()=>adapter.setScene({layout:fixture.layout,assetCatalog:fixture.catalog})')
                        print('Verified '+name, flush=True)
                    page.evaluate('adapter.dispose()')
                    page.close()
                assert not errors, errors
            finally:
                browser.close()
        assert LAYOUT.read_bytes() == raw and (ROOT/PRIVATE_ASSET_MANIFEST).read_bytes() == catalog_raw
        report.update(status='preview-verified', captures=shots, savedLayoutUnchanged=True, libraryUnchanged=True)
    except Exception as exc:
        report.update(status='failed', error=str(exc), browserErrors=errors)
        raise
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
        write('report.json', report)
    print(json.dumps(dict(status=report['status'], captures=len(shots), savedLayoutUnchanged=True)), flush=True)


if __name__ == '__main__':
    render()
