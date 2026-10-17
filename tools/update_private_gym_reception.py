"""Revision-bound reception replacement; preserve all other gym content."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools'),
    str(Path.home() / 'AppData/Roaming/Python/Python314/site-packages'),
    str(ROOT / '.runtime/model-import-20261002/mesh-dependencies')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.add_private_gym_calisthenics import yaw
from tools.add_private_gym_fitness_centre import footprint
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT = ROOT / '.runtime/private-gym-reception-20261009'
DESK = 'asset-gym-reception-set'
SOFA = 'asset-gym-wellness-sofa-apex'
REMOVED = {
    'pl-7aa4ceb85cebf8fe1a4f615a': 'asset-gym-commercial-pool-table',
    'pl-0c131d38c40292ce6b8bb6ac': 'asset-desk-1400-clear-wood',
    'pl-3e62d36f0ebdfeaa537fadcd': 'asset-chair-black',
}
ADDED = {'pl-gym-reception-set', 'pl-gym-reception-lion-sofa'}


def operations(before, catalog):
    by_id = {p['placementId']: p for p in before['placements']}
    assert not ADDED.intersection(by_id), 'Reception replacement already installed'
    for pid, aid in REMOVED.items():
        assert by_id[pid]['assetId'] == aid, 'Reviewed reception furniture changed'
    flag = by_id['pl-2f8c760de4adbb1a83cc1629']
    assert flag['assetId'] == 'asset-private-gym-reception-congo-mural'
    assert flag['transform']['position'] == dict(x=6, y=0, z=.3)
    settings = before['extensions']['facilityPerimeterWalls']['settings']
    lion = next(a for a in settings['exteriorFinish']['artworks'] if a['artworkId'] == 'apex-interior-a01')
    assert lion['edge'] == 3 and lion['side'] == 'interior'
    assert abs(lion['startMeters'] + lion['widthMeters']/2 - 23) < 1e-6
    ops = [dict(op='delete_placement', placementId=pid) for pid in REMOVED]
    for pid, aid, label, x, z, angle in [
        ('pl-gym-reception-set', DESK, 'Reception Set - Congo Flag', 6, 2.4, 0),
        ('pl-gym-reception-lion-sofa', SOFA, 'Reception Sofa - Lion Wall', .7, 7, 90),
    ]:
        ops.append(dict(op='place_asset', placement=dict(placementId=pid, assetId=aid,
            assetDefinitionRevision=catalog[aid]['assetDefinitionRevision'], positionMode='manual',
            transform=dict(position=dict(x=x, y=0, z=z), quaternion=yaw(angle), scale=1),
            snapRelationship=None, metadata=dict(instanceLabel=label, inputMethod='independent-authoring'))))
    return ops


def audit(before, after, catalog):
    old = {p['placementId']: p for p in before['placements']}
    new = {p['placementId']: p for p in after['placements']}
    assert old.keys() - new.keys() == REMOVED.keys()
    assert new.keys() - old.keys() == ADDED
    assert all(new[pid] == p for pid, p in old.items() if pid not in REMOVED), 'Unrelated placement changed'
    expected = {o['placement']['placementId']: o['placement'] for o in operations(before, catalog) if o['op'] == 'place_asset'}
    assert all(new[pid] == p for pid, p in expected.items())
    for key, value in before.items():
        if key not in {'placements', 'updatedAt'}:
            assert after[key] == value, ('Unrelated layout change', key)
    bounds = {pid: footprint(new[pid], catalog) for pid in ADDED}
    for x0, z0, x1, z1 in bounds.values():
        assert .09 < x0 < x1 < 12 and .375 < z0 < z1 < 10
    desk = bounds['pl-gym-reception-set']
    sofa = bounds['pl-gym-reception-lion-sofa']
    assert abs((desk[0] + desk[2])/2 - 6) < 1e-6
    assert desk[1] - .375 > 1.2, 'Rear reception access narrowed'
    assert sofa[2] < 1.1 and desk[3] + 2 < sofa[1], 'Waiting area obstructed'
    assert 'pl-gym-pool-swimming-pool' in new and 'pl-gym-pool-corner-jacuzzi' in new
    return dict(removed=list(REMOVED), added=sorted(ADDED), footprints=bounds,
        rearDeskAccessMeters=desk[1]-.375, preservedPlacements=len(old)-len(REMOVED),
        swimmingPoolUnchanged=True, artworkAndRoomGeometryUnchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'publish-assets', 'save', 'verify-saved'])
    parser.add_argument('--review-attempt', type=int, default=1)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    target = STORE / 'layouts/local/site-local/layouts' / (LAYOUT + '.json')
    manifest, staged = ROOT / PRIVATE_ASSET_MANIFEST, OUT / 'staged-project'
    if args.phase == 'verify-saved':
        saved = json.loads((OUT / 'saved.json').read_bytes())
        assert saved == json.loads(target.read_bytes())
        assert 1 <= args.review_attempt <= 5
        review = OUT / ('saved-review' if args.review_attempt == 1 else 'saved-review-' + str(args.review_attempt))
        profile = json.loads((OUT / 'profile.json').read_text())
        profile.update(profileId='private-gym-reception-saved-' + str(args.review_attempt),
            origin='http://127.0.0.1:' + str(8572 + args.review_attempt),
            dataRoot=str(review), backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()))
        config = json.loads((OUT / 'review-config.json').read_text())
        config.update(profileId=profile['profileId'], verifySavedOnly=True)
        for name in ['before.json', 'candidate.json', 'saved.json']:
            write(review / name, saved)
        write(review / 'profile.json', profile)
        write(review / 'review-config.json', config)
        print(str(review / 'profile.json'))
        return
    if args.phase != 'stage':
        report = json.loads((OUT / 'report.json').read_text())
        assert target.read_bytes() == (OUT / 'before.json').read_bytes(), 'Saved gym changed'
        if args.phase == 'publish-assets':
            assert report['status'] == 'validated'
            assert manifest.read_bytes() == (OUT / 'catalog-before.json').read_bytes(), 'Catalog changed'
            RevisionedAuthorityRepository._atomic_write(manifest, (staged / PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status'] = 'assets-published'
        else:
            assert report['status'] == 'assets-published'
            raw = (OUT / 'candidate.json').read_bytes()
            proof = json.loads((OUT / 'native-check.json').read_text())
            assert proof['status'] == 'preview-verified' and proof['candidateHash'] == hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes() == (staged / PRIVATE_ASSET_MANIFEST).read_bytes()
            for rel, digest in report['assetHashes'].items():
                assert hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
                audit(json.loads((OUT / 'before.json').read_bytes()), json.loads(raw), catalog)
                receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, json.loads(raw), report['baseRevision'])
            finally:
                host.close()
            write(OUT / 'saved.json', receipt['layout'])
            report.update(status='saved', savedRevision=receipt['revision'])
            hashes = saved_hashes()
            assert all(hashes[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name, 'registry.json'))
            report['otherLayoutsUnchanged'] = True
        write(OUT / 'report.json', report)
        print(report['status'])
        return
    raw, catalog_raw = target.read_bytes(), manifest.read_bytes()
    before, library = json.loads(raw), json.loads(catalog_raw)
    for name, data in [('before.json', raw), ('catalog-before.json', catalog_raw)]:
        file = OUT / name
        if file.exists():
            assert file.read_bytes() == data, 'Base changed'
        else:
            file.write_bytes(data)
    entry = json.loads((ROOT / 'generated/industrial_assets/local_library/gym-reception-set/catalog-entry.json').read_text())
    assert entry['assetId'] == DESK and entry['source']['fileName'] == 'reception set.STL'
    assert not any(e['assetId'] == DESK for e in library['assets'])
    library['assets'].append(entry)
    library['summary']['total'] = len(library['assets'])
    write(staged / PRIVATE_ASSET_MANIFEST, library)
    stage = OUT / 'validation-store'
    for rel in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE / rel), _native_fs_path(stage / rel), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=staged)
    try:
        catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
        ops = operations(before, catalog)
        write(OUT / 'operations.json', ops)
        candidate = apply_facility_layout_operations(before, ops, updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks = audit(before, candidate, catalog)
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT / 'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
    finally:
        host.close()
    write(OUT / 'candidate.json', receipt['layout'])
    write(OUT / 'report.json', dict(status='validated', baseRevision=layout_revision(before), layoutHashes=saved_hashes(), checks=checks,
        assetHashes={entry['artifact']: hashlib.sha256((ROOT / entry['artifact']).read_bytes()).hexdigest()},
        limitations=['Unitless reception STL provisionally interpreted as centimetres; physical dimensions require confirmation.']))
    profile = json.loads((ROOT / '.runtime/private-gym-showroom-20261009/profile.json').read_text())
    profile.update(profileId='private-gym-reception', origin='http://127.0.0.1:8572', dataRoot=str(OUT),
        backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()))
    write(OUT / 'profile.json', profile)
    def shot(name, p, t):
        return dict(name=name, position=dict(zip(('x', 'y', 'z'), p)), target=dict(zip(('x', 'y', 'z'), t)), thresholds=dict(detail=1000))
    write(OUT / 'review-config.json', dict(profileId=profile['profileId'], minimumAssetMeshes=1, cameraFov=55,
        requiredAssets=[DESK, SOFA], shots=[
            shot('01-reception-front', (6, 2.1, 7.3), (6, 1.35, .7)),
            shot('02-lion-waiting-area', (5.2, 2.3, 8.9), (.2, 1.55, 7)),
            shot('03-entrance-overview', (11.3, 7.4, 12.2), (5.2, .5, 4.9)),
            shot('04-staff-side', (7.9, 1.9, .85), (6.1, .65, 2.4))],
        finalShot=shot('05-saved-reception', (9.7, 3.4, 10.7), (4.6, 1.3, 2.8))))
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
