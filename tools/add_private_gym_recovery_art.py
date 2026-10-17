"""Attach three alpha artworks to existing recovery walls; review before saving."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from PIL import Image
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT = ROOT/'.runtime/private-gym-recovery-art-20261009'
WEST_WALL = 'pl-c57cb8a4a0b92614d2731649'
SPECS = [
    dict(id='recovery-wolf', file='ChatGPT Image Oct 9, 2026, 12_24_42 AM-1.png',
        target=dict(placementId=WEST_WALL, face='positive_z'), region=[0, 0, 1, 1]),
    dict(id='recovery-discipline', file='ChatGPT Image Oct 9, 2026, 12_24_43 AM-2.png',
        target=dict(edge=0, side='interior'), region=[54.35/60, 0, 59.85/60, 1]),
    dict(id='recovery-ocean', file='ChatGPT Image Oct 9, 2026, 12_24_45 AM-3.png',
        target=dict(edge=1, side='interior'), region=[.15/30, 0, 9.45/30, 1]),
]


def prepare():
    records, sources = [], []
    for spec in SPECS:
        source = Path.home()/'Downloads'/spec['file']
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        rel = 'generated/facility-wall-art/'+digest+'.png'
        with Image.open(source) as image:
            assert image.mode == 'RGBA', 'Original artwork must have PNG alpha'
            alpha = image.getchannel('A')
            assert alpha.getextrema()[0] == 0, 'Artwork needs a transparent background'
            # Match the renderer's 0.01 alpha cutoff; isolated invisible residue must not shrink the art.
            box = alpha.point(lambda value: 255 if value >= 3 else 0).getbbox()
            assert box
            w, h = image.size
            box = (max(0,box[0]-2), max(0,box[1]-2), min(w,box[2]+2), min(h,box[3]+2))
            # Trim transparent margins in texture coordinates, never resample or rewrite the PNG.
            uv = [box[0]/w, 1-box[3]/h, box[2]/w, 1-box[1]/h]
        dest = OUT/'staged-project'/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        records.append(dict(artworkId=spec['id'], imagePath='/'+rel, uv=uv,
            target=spec['target'], region=spec['region'], coverage=.97))
        sources.append(dict(artworkId=spec['id'], file=spec['file'], artifact=rel, sha256=digest,
            originalPixels=[w,h], alphaBounds=list(box), alphaThreshold=3, originalImageUnmodified=True))
    return records, sources


def build(before, records):
    settings = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    finish = settings['exteriorFinish']
    existing = finish.setdefault('fittedArtworks', [])
    assert not {a['artworkId'] for a in existing}.intersection(a['artworkId'] for a in records)
    existing.extend(records)
    return apply_facility_layout_operations(before,
        [dict(op='set_perimeter_walls', wallSettings=settings)])['document']


def audit(before, after, records):
    expected = deepcopy(before)
    expected['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish'].setdefault('fittedArtworks', []).extend(records)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Content beyond three fitted recovery graphics changed'
    return dict(artworks=3, unchangedPlacements=len(before['placements']),
        wallGeometryAndColorsUnchanged=True, otherArtworkUnchanged=True, imagesUnmodified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage','publish-images','save'])
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
            for item in report['sources']:
                raw = (OUT/'staged-project'/item['artifact']).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == item['sha256']
                dest = ROOT/item['artifact']
                if dest.exists(): assert dest.read_bytes() == raw
                else: RevisionedAuthorityRepository._atomic_write(dest, raw)
            report['status'] = 'images-published'
        else:
            assert report['status'] == 'images-published'
            raw = (OUT/'candidate.json').read_bytes()
            proof = json.loads((OUT/'native-check.json').read_text())
            assert proof['status'] == 'preview-verified'
            assert proof['candidateHash'] == hashlib.sha256(raw).hexdigest()
            assert proof.get('responsiveArtworkVerified') is True
            for item in report['sources']:
                assert hashlib.sha256((ROOT/item['artifact']).read_bytes()).hexdigest() == item['sha256']
            before = json.loads((OUT/'before.json').read_bytes())
            candidate = json.loads(raw)
            audit(before, candidate, report['records'])
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
                audit(before, receipt['layout'], report['records'])
            finally: host.close()
            write(OUT/'saved.json', receipt['layout'])
            report.update(status='saved', savedRevision=receipt['revision'])
            hashes = saved_hashes()
            assert all(hashes[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged'] = True
        write(OUT/'report.json', report)
        print(report['status'])
        return
    before_raw = target.read_bytes()
    before = json.loads(before_raw)
    for name, raw in [('before.json',before_raw),('catalog-before.json',manifest.read_bytes())]:
        path = OUT/name
        if path.exists(): assert path.read_bytes() == raw, 'Source changed since staging'
        else: path.write_bytes(raw)
    records, sources = prepare()
    candidate = build(before, records)
    checks = audit(before, candidate, records)
    stage = OUT/'validation-store'
    for folder in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(stage/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=ROOT)
    try:
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT/'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
        audit(before, receipt['layout'], records)
    finally: host.close()
    write(OUT/'candidate.json', receipt['layout'])
    write(OUT/'report.json', dict(status='validated', baseRevision=layout_revision(before),
        layoutHashes=saved_hashes(), sources=sources, records=records, checks=checks))
    profile = json.loads((ROOT/'.runtime/private-gym-pool-side-art-20261009/profile.json').read_text())
    profile.update(profileId='private-gym-recovery-art', origin='http://127.0.0.1:8566', dataRoot=str(OUT),
        backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()))
    write(OUT/'profile.json', profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    entrance = shot('04-recovery-room', (57.8,2,9.15), (57.2,1.6,1.4))
    write(OUT/'review-config.json', dict(profileId=profile['profileId'],requiredAssets=[],cameraFov=50,
        requiredWallArt=[s['id'] for s in SPECS], fittedArtworkProbe=dict(placementId=WEST_WALL,
            placedArtworkId='recovery-wolf', perimeterArtworkId='recovery-ocean'), shots=[
            shot('01-left-recovery-wolf',(58.9,1.9,3.5),(54.29,1.5,3.5)),
            shot('02-back-discipline',(57.1,2,6),(57.1,1.8,.1)),
            shot('03-right-ocean',(54.7,1.9,4.8),(59.9,1.8,4.8)),entrance],
        finalShot=dict(entrance,name='05-saved-recovery')))
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
