"""Attach five supplied warriors to the measured Private Gym corridor walls."""
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
from tools.add_private_gym_outdoor_art import alpha_uv
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT = ROOT/'.runtime/private-gym-warrior-hall-20261010'
SOURCE = Path.home()/'Downloads/super hero'
SPECS = [
    ('viking', 'ChatGPT Image Oct 10, 2026, 09_21_51 AM-3.png'),
    ('zulu', 'ChatGPT Image Oct 10, 2026, 09_21_52 AM-4.png'),
    ('samurai', 'ChatGPT Image Oct 10, 2026, 09_21_51 AM-2.png'),
    ('mongol-archer', 'ChatGPT Image Oct 10, 2026, 09_21_53 AM-6.png'),
    ('spartan', 'ChatGPT Image Oct 10, 2026, 09_21_50 AM-1.png'),
]
GALLERY = ['pl-gym-wellness-'+name for name in (
    'lounge-north-left', 'lounge-north-right', 'conf-north-left',
    'conf-north-right', 'work-north-left', 'work-north-right')]
END = 'pl-gym-wellness-corridor-west'
CORRIDOR = 'zn-gym-wellness-corridor'


def measured_wall(doc, catalog, pid):
    p = next(p for p in doc['placements'] if p['placementId'] == pid)
    a = catalog[p['assetId']]
    assert a['assetDefinitionRevision'] == p['assetDefinitionRevision']
    assert p['transform']['scale'] == 1
    assert p['transform']['quaternion'] == dict(x=0, y=0, z=0, w=1)
    assert 'wall' in a.get('tags', []) + a['definition'].get('tags', [])
    return p, a['definition']['geometry']['aabb']


def prepare():
    sources = []
    for name, filename in SPECS:
        raw = (SOURCE/filename).read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        artifact = 'generated/facility-wall-art/'+digest+'.png'
        with Image.open(SOURCE/filename) as image:
            uv, box = alpha_uv(image)
            pixels = list(image.size)
        dest = OUT/'staged-project'/artifact
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        sources.append(dict(name=name, file=filename, artifact=artifact, sha256=digest,
            originalPixels=pixels, alphaBounds=list(box), uv=uv, originalImageUnmodified=True))
    return sources


def plan(doc, catalog, sources):
    corridor = next(z for z in doc['zones'] if z['zoneId'] == CORRIDOR)
    low = min(p['x'] for p in corridor['boundary'])
    high = max(p['x'] for p in corridor['boundary'])
    north = min(p['z'] for p in corridor['boundary'])
    records, measurements, occupied = [], [], []
    for index, source in enumerate(sources):
        guardian = source['name'] == 'spartan'
        fraction = .92 if guardian else .825
        box = source['alphaBounds']
        ratio = (box[2]-box[0])/(box[3]-box[1])
        candidates = []
        # The screenshot's closed end is west; the sequence approaches it from the office/pool end.
        desired = high-(index+.5)*(high-low)/4 if not guardian else None
        for pid in [END] if guardian else GALLERY:
            p, bounds = measured_wall(doc, catalog, pid)
            pos = p['transform']['position']
            axis = 'z' if guardian else 'x'
            minimum, maximum = bounds['minimum'], bounds['maximum']
            height = maximum['y']-minimum['y']
            width = height*fraction*ratio
            start, end = (pos[axis]+b[axis] for b in (minimum, maximum))
            if not guardian:
                assert abs(pos['z']-north) < 1e-5, 'Gallery wall no longer borders the corridor'
            if end-start < width+.15:
                continue
            center = (start+end)/2 if guardian else max(start+width/2+.075, min(end-width/2-.075, desired))
            if any(center-width/2 < b+.15 and center+width/2 > a-.15 for a, b in occupied):
                continue
            candidates.append((0 if guardian else abs(center-desired), pid, p, bounds, center, width, height))
        assert candidates, 'No uninterrupted wall can fit '+source['name']
        _, pid, p, bounds, center, width, height = min(candidates, key=lambda row: (row[0], row[1]))
        axis = 'z' if guardian else 'x'
        start = p['transform']['position'][axis]+bounds['minimum'][axis]
        length = bounds['maximum'][axis]-bounds['minimum'][axis]
        region = [(center-width/2-start)/length, .025, (center+width/2-start)/length, .025+fraction]
        record = dict(artworkId='hall-warrior-'+source['name'], imagePath='/'+source['artifact'],
            target=dict(placementId=pid, face='positive_x' if guardian else 'positive_z'),
            region=region, coverage=1, uv=source['uv'])
        records.append(record)
        measurements.append(dict(artworkId=record['artworkId'], placementId=pid,
            assetDefinitionRevision=p['assetDefinitionRevision'], transform=p['transform'], bounds=bounds,
            face=record['target']['face'], centerAlongWall=center, widthMeters=width,
            heightMeters=height*fraction, wallHeightMeters=height, bottomMeters=.025*height,
            desiredCenter=desired))
        if not guardian:
            occupied.append((center-width/2, center+width/2))
    assert all(a['centerAlongWall'] > b['centerAlongWall'] for a, b in zip(measurements[:3], measurements[1:4]))
    return records, measurements


def build(before, records):
    settings = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    existing = settings['exteriorFinish'].setdefault('fittedArtworks', [])
    assert not {a['artworkId'] for a in existing}.intersection(a['artworkId'] for a in records)
    existing.extend(records)
    return apply_facility_layout_operations(before, [dict(op='set_perimeter_walls', wallSettings=settings)])['document']


def audit(before, after, records):
    expected = deepcopy(before)
    expected['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish'].setdefault('fittedArtworks', []).extend(records)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unexpected change outside the five new wall graphics'
    assert [r['artworkId'] for r in records] == ['hall-warrior-'+s[0] for s in SPECS]
    assert all(r['target']['placementId'] in GALLERY and r['target']['face'] == 'positive_z' for r in records[:4])
    assert records[-1]['target'] == dict(placementId=END, face='positive_x')
    return dict(artworks=5, unchangedPlacements=len(before['placements']), geometryUnchanged=True,
        entrancesUnchanged=True, oppositeBrandingUnchanged=True, originalImagesUnmodified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'publish-images', 'save'])
    phase = parser.parse_args().phase
    OUT.mkdir(parents=True, exist_ok=True)
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    if phase != 'stage':
        report = json.loads((OUT/'report.json').read_bytes())
        assert target.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed since staging'
        assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes(), 'Library changed since staging'
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
            proof = json.loads((OUT/'browser-check.json').read_bytes())
            assert proof['status'] == 'passed' and proof['candidateHash'] == hashlib.sha256(raw).hexdigest()
            assert proof['responsiveArtworkVerified'] is True
            before, candidate = json.loads((OUT/'before.json').read_bytes()), json.loads(raw)
            audit(before, candidate, report['records'])
            for source in report['sources']:
                assert hashlib.sha256((ROOT/source['artifact']).read_bytes()).hexdigest() == source['sha256']
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
                assert plan(before, catalog, report['sources']) == (report['records'], report['measurements'])
                receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
                audit(before, receipt['layout'], report['records'])
                assert json.loads(target.read_bytes()) == receipt['layout']
            finally:
                host.close()
            write(OUT/'saved.json', receipt['layout'])
            hashes = saved_hashes()
            assert all(hashes[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name, 'registry.json'))
            report.update(status='saved', savedRevision=receipt['revision'], otherLayoutsUnchanged=True,
                savedDocumentReloadMatches=True)
        write(OUT/'report.json', report)
        print(report['status'])
        return
    before = json.loads(target.read_bytes())
    for name, raw in [('before.json', target.read_bytes()), ('catalog-before.json', manifest.read_bytes())]:
        file = OUT/name
        if file.exists():
            assert file.read_bytes() == raw, 'Source changed since staging'
        else:
            file.write_bytes(raw)
    sources = prepare()
    stage = OUT/'validation-store'
    for folder in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(stage/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = host.authoritative_asset_catalog()
        records, measurements = plan(before, {a['assetId']: a for a in catalog}, sources)
        candidate = build(before, records)
        checks = audit(before, candidate, records)
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT/'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
        audit(before, receipt['layout'], records)
    finally:
        host.close()
    write(OUT/'candidate.json', receipt['layout'])
    write(OUT/'report.json', dict(status='validated', baseRevision=layout_revision(before),
        layoutHashes=saved_hashes(), sources=sources, records=records, measurements=measurements, checks=checks,
        sourceScreenshot='C:/Users/might/Downloads/Video/20.png',
        approach='From the office/pool end towards the closed west end; original PNG poses retained'))
    fixture = deepcopy(receipt['layout'])
    # Include all corridor segments and the branded opposite perimeter for occlusion checks.
    ids = set(GALLERY+[END, 'pl-gym-pool-connection-north', 'pl-gym-pool-connection-south'])
    fixture['placements'] = [p for p in fixture['placements'] if p['placementId'] in ids]
    fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['fittedArtworks'] = records
    fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['wallFaces'] = []
    aids = {p['assetId'] for p in fixture['placements']}
    library = {a['assetId']: a for a in json.loads(manifest.read_bytes())['assets']}
    artifacts = {aid: dict(url='/'+library[aid]['artifact'], sourceToCanonical=library[aid]['sourceToCanonical']) for aid in aids}
    write(OUT/'render-fixture.json', dict(layout=fixture, catalog=[a for a in catalog if a['assetId'] in aids],
        artifacts=artifacts, ids=[r['artworkId'] for r in records], sources=sources, measurements=measurements))
    print(json.dumps(dict(checks=checks, measurements=measurements)))


if __name__ == '__main__':
    main()
