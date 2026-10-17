"""Add the two original transparent artworks to the pool's inward side walls."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'),
    str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.industrial_assets.artifacts import inspect_glb
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write, saved_hashes
from tools.private_gym_reception_art import wall_glb
from tools.apex_equipment_materials import unpack, pack

OUT = ROOT/'.runtime/private-gym-pool-side-art-20261009'
WALLS = [
    dict(placement='pl-gym-pool-east-wall', asset='asset-gym-pool-east-wall-shark',
        name='Shark', inward=-1, file='ChatGPT Image Oct 9, 2026, 12_07_17 AM-2.png'),
    dict(placement='pl-gym-pool-connection-south', asset='asset-gym-pool-west-wall-orca',
        name='Orca', inward=1, file='ChatGPT Image Oct 9, 2026, 12_07_17 AM-1.png'),
]


def side_wall_glb(png, dimensions, inward, name):
    assert inward in (-1, 1)
    local = dict(width=dimensions['depth'], depth=dimensions['width'], height=dimensions['height'])
    doc, data = unpack(wall_glb(png, local, fit='contain', face=1, name=name))
    # Rotate the authored mesh, not the placement: its existing X/Z envelope stays exact.
    root = len(doc['nodes'])
    doc['nodes'].append(dict(name='Inward pool wall artwork', children=doc['scenes'][0]['nodes'],
        matrix=[0,0,-inward,0, 0,1,0,0, inward,0,0,0, 0,0,0,1]))
    doc['scenes'][0]['nodes'] = [root]
    raw = pack(doc, data)
    bounds = inspect_glb(raw).aabb
    for axis, size in [('x', dimensions['width']), ('y', dimensions['height']), ('z', dimensions['depth'])]:
        assert abs(bounds['maximum'][axis]-bounds['minimum'][axis]-size) < 1e-5
    assert png in raw
    return raw


def prepare(before, library):
    artifacts = []
    for spec in WALLS:
        wall = next(p for p in before['placements'] if p['placementId'] == spec['placement'])
        old = next(a for a in library['assets'] if a['assetId'] == wall['assetId'])
        assert old['sourceToCanonical'] == IDENTITY
        assert not any(a['assetId'] == spec['asset'] for a in library['assets'])
        source = Path.home()/'Downloads'/spec['file']
        png = source.read_bytes()
        raw = side_wall_glb(png, old['dimensions'], spec['inward'], spec['name'])
        rel = 'generated/industrial_assets/private_gym/pool-art/' + spec['name'].lower() + '-' + hashlib.sha256(raw).hexdigest()[:16] + '.glb'
        dest = OUT/'staged-project'/rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(raw)
        asset = deepcopy(old)
        asset.update(assetId=spec['asset'], displayName='APEX Pool Wall - '+spec['name'], artifact=rel,
            description='Original transparent pool artwork on the inward wall face; unchanged wall envelope.',
            source=dict(kind='authored-textured-wall', originalFile=spec['file'],
                sha256=hashlib.sha256(png).hexdigest(), imageModified=False, previousAssetId=old['assetId']))
        library['assets'].append(asset)
        artifacts.append(rel)
    library['summary']['total'] = len(library['assets'])
    write(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST, library)
    return artifacts


def build(before, catalog):
    candidate = deepcopy(before)
    for spec in WALLS:
        wall = next(p for p in candidate['placements'] if p['placementId'] == spec['placement'])
        wall.update(assetId=spec['asset'], assetDefinitionRevision=catalog[spec['asset']]['assetDefinitionRevision'])
    candidate['updatedAt'] = datetime.now(timezone.utc).isoformat()
    return candidate


def audit(before, after, catalog):
    expected = build(before, catalog)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Content beyond the two pool wall asset bindings changed'
    for spec in WALLS:
        wall = next(p for p in before['placements'] if p['placementId'] == spec['placement'])
        old = catalog[wall['assetId']]['definition']['geometry']['aabb']
        new = catalog[spec['asset']]['definition']['geometry']['aabb']
        for endpoint in ('minimum', 'maximum'):
            for axis in ('x', 'y', 'z'):
                assert abs(old[endpoint][axis]-new[endpoint][axis]) < 1e-5
    return dict(artworkWalls=2, placementCount=len(after['placements']),
        geometryAndTransformsUnchanged=True, otherArtworkUnchanged=True, originalPngsUnmodified=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'publish-assets', 'save'])
    phase = parser.parse_args().phase
    OUT.mkdir(parents=True, exist_ok=True)
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    staged = OUT/'staged-project'
    if phase != 'stage':
        report = json.loads((OUT/'report.json').read_text())
        assert target.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed'
        if phase == 'publish-assets':
            assert report['status'] == 'validated'
            assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes()
            for rel, digest in report['assetHashes'].items():
                raw = (staged/rel).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == digest
                dest = ROOT/rel
                if dest.exists():
                    assert dest.read_bytes() == raw
                else:
                    RevisionedAuthorityRepository._atomic_write(dest, raw)
            RevisionedAuthorityRepository._atomic_write(manifest, (staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status'] = 'assets-published'
        else:
            assert report['status'] == 'assets-published'
            raw = (OUT/'candidate.json').read_bytes()
            proof = json.loads((OUT/'native-check.json').read_text())
            assert proof['status'] == 'preview-verified'
            assert proof['candidateHash'] == hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes() == (staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for rel, digest in report['assetHashes'].items():
                assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest() == digest
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
                before = json.loads((OUT/'before.json').read_bytes())
                audit(before, json.loads(raw), catalog)
                receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, json.loads(raw), report['baseRevision'])
                audit(before, receipt['layout'], catalog)
            finally:
                host.close()
            write(OUT/'saved.json', receipt['layout'])
            report.update(status='saved', savedRevision=receipt['revision'])
            hashes = saved_hashes()
            assert all(hashes[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name, 'registry.json'))
            report['otherLayoutsUnchanged'] = True
        write(OUT/'report.json', report)
        print(report['status'])
        return
    raw = target.read_bytes()
    before = json.loads(raw)
    catalog_raw = manifest.read_bytes()
    for name, payload in [('before.json', raw), ('catalog-before.json', catalog_raw)]:
        path = OUT/name
        if path.exists():
            assert path.read_bytes() == payload, 'Source changed since staging: '+name
        else:
            path.write_bytes(payload)
    artifacts = prepare(before, json.loads(catalog_raw))
    stage = OUT/'validation-store'
    for folder in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(stage/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=staged)
    try:
        catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
        candidate = build(before, catalog)
        checks = audit(before, candidate, catalog)
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT/'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
        audit(before, receipt['layout'], catalog)
    finally:
        host.close()
    write(OUT/'candidate.json', receipt['layout'])
    write(OUT/'report.json', dict(status='validated', baseRevision=layout_revision(before),
        layoutHashes=saved_hashes(), artifacts=artifacts, checks=checks,
        assetHashes={rel: hashlib.sha256((staged/rel).read_bytes()).hexdigest() for rel in artifacts}))
    profile = json.loads((ROOT/'.runtime/private-gym-art-visibility-20261008/profile.json').read_text())
    profile.update(profileId='private-gym-pool-side-art', origin='http://127.0.0.1:8565', dataRoot=str(OUT),
        backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()))
    write(OUT/'profile.json', profile)
    def shot(name, p, t):
        return dict(name=name, position=dict(zip(('x','y','z'), p)), target=dict(zip(('x','y','z'), t)), thresholds=dict(detail=1000))
    overview = shot('03-pool-art-context', (42.7,9,-20.5), (42.7,.7,-7))
    write(OUT/'review-config.json', dict(profileId=profile['profileId'], minimumAssetMeshes=2,
        requiredAssets=[s['asset'] for s in WALLS], requiredWallArt=['higher-everyday'], shots=[
            shot('01-east-shark', (44,1.7,-8.934), (49.76,1.6,-8.934)),
            shot('02-west-orca', (41.5,1.7,-10.187), (36,1.6,-10.187)), overview],
        finalShot=dict(overview, name='04-saved-pool-art')))
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
