"""Fit the user's two murals to the reviewed outdoor-facing gym walls."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT = ROOT/'.runtime/private-gym-outdoor-art-20261009'
SPECS = [
    dict(id='outdoor-apex-wolf', file='Apex Outdoor Wolf Mountain Emblem.png',
        placement='pl-private-gym-fields-east-north', asset='asset-private-gym-fields-east-north',
        position=dict(x=41.85, y=0, z=50.45), yaw90=True, width=22.5, height=6.2),
    dict(id='outdoor-peak-performance', file='Black and Gold Peak Performance Mural.png',
        placement='pl-private-gym-sports-court-back',
        asset='asset-private-gym-apex-court-back-branding-only-centered',
        position=dict(x=71.5, y=0, z=36.15), yaw90=False, width=19.6, height=5.5),
]


def alpha_uv(image):
    assert image.mode == 'RGBA', 'Artwork must have PNG transparency'
    alpha = image.getchannel('A')
    assert alpha.getextrema()[0] == 0
    box = alpha.point(lambda v: 255 if v >= 3 else 0).getbbox()
    assert box, 'Empty artwork'
    w, h = image.size
    box = (max(0, box[0]-2), max(0, box[1]-2), min(w, box[2]+2), min(h, box[3]+2))
    return [box[0]/w, 1-box[3]/h, box[2]/w, 1-box[1]/h], box


def prepare():
    records, sources = [], []
    for spec in SPECS:
        source = Path.home()/'Downloads'/spec['file']
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        rel = 'generated/facility-wall-art/'+digest+'.png'
        with Image.open(source) as image:
            uv, box = alpha_uv(image)
            pixels = list(image.size)
        dest = OUT/'staged-project'/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        records.append(dict(artworkId=spec['id'], imagePath='/'+rel, uv=uv,
            target=dict(placementId=spec['placement'], face='positive_z'),
            region=[0, 0, 1, 1], coverage=.98))
        sources.append(dict(artworkId=spec['id'], file=spec['file'], artifact=rel, sha256=digest,
            originalPixels=pixels, alphaBounds=list(box), originalImageUnmodified=True))
    return records, sources


def check_targets(before, catalog):
    by_id = {p['placementId']: p for p in before['placements']}
    for spec in SPECS:
        p = by_id[spec['placement']]
        assert p['assetId'] == spec['asset'] and p['transform']['position'] == spec['position'], 'Reviewed wall changed'
        assert p['transform']['scale'] == 1
        q = p['transform']['quaternion']
        expected = dict(x=0, y=.707106781, z=0, w=.707106781) if spec['yaw90'] else dict(x=0, y=0, z=0, w=1)
        assert q == expected, 'Reviewed wall orientation changed'
        a = catalog[p['assetId']]
        assert a['assetDefinitionRevision'] == p['assetDefinitionRevision']
        b = a['definition']['geometry']['aabb']
        assert abs(b['maximum']['x']-b['minimum']['x']-spec['width']) < 1e-5
        assert abs(b['maximum']['y']-b['minimum']['y']-spec['height']) < 1e-5


def build(before, records):
    settings = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    existing = settings['exteriorFinish'].setdefault('fittedArtworks', [])
    assert not {a['artworkId'] for a in existing}.intersection(a['artworkId'] for a in records)
    existing.extend(records)
    return apply_facility_layout_operations(before,
        [dict(op='set_perimeter_walls', wallSettings=settings)])['document']


def audit(before, after, records):
    assert [r['artworkId'] for r in records] == [s['id'] for s in SPECS]
    for record, spec in zip(records, SPECS):
        assert record['target'] == dict(placementId=spec['placement'], face='positive_z')
        assert record['coverage'] == .98 and record['region'] == [0, 0, 1, 1]
    expected = deepcopy(before)
    expected['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish'].setdefault('fittedArtworks', []).extend(records)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Content beyond the two outdoor murals changed'
    return dict(artworks=2, unchangedPlacements=len(before['placements']),
        wallGeometryAndColorsUnchanged=True, existingArtworkUnchanged=True,
        originalImagesUnmodified=True, coverage=.98)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'publish-images', 'save'])
    phase = parser.parse_args().phase
    OUT.mkdir(parents=True, exist_ok=True)
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    if phase != 'stage':
        report = json.loads((OUT/'report.json').read_text())
        assert target.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed'
        assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes(), 'Equipment library changed'
        if phase == 'publish-images':
            assert report['status'] == 'validated'
            for source in report['sources']:
                raw = (OUT/'staged-project'/source['artifact']).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == source['sha256']
                dest = ROOT/source['artifact']
                if dest.exists():
                    assert dest.read_bytes() == raw
                else:
                    RevisionedAuthorityRepository._atomic_write(dest, raw)
            report['status'] = 'images-published'
        else:
            assert report['status'] == 'images-published'
            raw = (OUT/'candidate.json').read_bytes()
            proof = json.loads((OUT/'browser-check.json').read_text())
            assert proof['status'] == 'passed' and proof['candidateHash'] == hashlib.sha256(raw).hexdigest()
            assert proof['responsiveArtworkVerified'] is True
            for source in report['sources']:
                assert hashlib.sha256((ROOT/source['artifact']).read_bytes()).hexdigest() == source['sha256']
            before, candidate = json.loads((OUT/'before.json').read_bytes()), json.loads(raw)
            audit(before, candidate, report['records'])
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                check_targets(candidate, {a['assetId']: a for a in host.authoritative_asset_catalog()})
                receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
                audit(before, receipt['layout'], report['records'])
                assert json.loads(target.read_bytes()) == receipt['layout']
            finally:
                host.close()
            write(OUT/'saved.json', receipt['layout'])
            hashes = saved_hashes()
            assert all(hashes[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name, 'registry.json'))
            report.update(status='saved', savedRevision=receipt['revision'], otherLayoutsUnchanged=True,
                savedDocumentReloadMatches=True, verificationScope='Real application Three.js renderer; focused wall scene, not whole-desktop qualification')
        write(OUT/'report.json', report)
        print(report['status'])
        return
    raw = target.read_bytes()
    before = json.loads(raw)
    for name, data in [('before.json', raw), ('catalog-before.json', manifest.read_bytes())]:
        path = OUT/name
        if path.exists():
            assert path.read_bytes() == data, 'Source changed since staging'
        else:
            path.write_bytes(data)
    records, sources = prepare()
    candidate = build(before, records)
    checks = audit(before, candidate, records)
    stage = OUT/'validation-store'
    for folder in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(stage/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = host.authoritative_asset_catalog()
        check_targets(before, {a['assetId']: a for a in catalog})
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT/'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
        audit(before, receipt['layout'], records)
    finally:
        host.close()
    write(OUT/'candidate.json', receipt['layout'])
    write(OUT/'report.json', dict(status='validated', baseRevision=layout_revision(before),
        layoutHashes=saved_hashes(), sources=sources, records=records, checks=checks))
    # The render fixture retains exact target geometry and transforms. It is not the saved document.
    fixture = deepcopy(receipt['layout'])
    ids = {s['placement'] for s in SPECS}
    fixture['placements'] = [p for p in fixture['placements'] if p['placementId'] in ids]
    fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'] = records
    fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks'] = []
    fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['wallFaces'] = []
    aids = {p['assetId'] for p in fixture['placements']}
    library = {a['assetId']: a for a in json.loads(manifest.read_bytes())['assets']}
    wall_catalog = [a for a in catalog if a['assetId'] in aids]
    artifacts = {aid: dict(url='/'+library[aid]['artifact'], sourceToCanonical=library[aid]['sourceToCanonical']) for aid in aids}
    write(OUT/'render-fixture.json', dict(layout=fixture, catalog=wall_catalog, artifacts=artifacts,
        ids=[s['id'] for s in SPECS], sources=sources))
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
