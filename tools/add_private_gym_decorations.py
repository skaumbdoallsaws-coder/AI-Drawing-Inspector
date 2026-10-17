"""Add the three approved APEX outdoor displays without moving existing equipment."""
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'),
    str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'),
    str(ROOT/'.runtime/model-import-20261002/mesh-dependencies')]
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.spatial import placement_spatial_records
from tools.add_private_gym_calisthenics import yaw
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from tools.import_private_gym_decorations import OUT

A = 'asset-gym-decoration-'
P = 'pl-gym-decoration-'
M = 'fm-gym-decoration-'
POSES = {'bull': (48.2,41.45,180), 'dog': (69.2,63.2,45), 'ducati': (78,51.5,270)}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def markings():
    result = []
    for key,x,z,w,d,color,y in [
        ('motorcycle-pad',78,51.5,4.5,3,'#17191c',.006),
        ('motorcycle-gold-west',75.75,51.5,.06,3,'#c99b39',.008),
        ('motorcycle-gold-east',80.25,51.5,.06,3,'#c99b39',.008),
        ('motorcycle-gold-south',78,50,4.5,.06,'#c99b39',.008),
        ('motorcycle-gold-north',78,53,4.5,.06,'#c99b39',.008)]:
        result.append(dict(markingId=M+key,markingType='solid_line',label='APEX '+key.replace('-',' '),
            semanticRole='decorative',positionMode='manual',transform=dict(position=dict(x=x,y=y,z=z),rotationDegrees=0),
            width=w,depth=d,fillColor=color,strokeColor=color,opacity=1,text='',evidence=[],
            metadata=dict(authoredIn='private-gym-decorations')))
    return result


def operations(catalog):
    ops = []
    for key,(x,z,angle) in POSES.items():
        entry = catalog[A+key]
        ops.append(dict(op='place_asset',placement=dict(placementId=P+key,assetId=A+key,
            assetDefinitionRevision=entry['assetDefinitionRevision'],positionMode='manual',
            transform=dict(position=dict(x=x,y=0,z=z),quaternion=yaw(angle),scale=1),snapRelationship=None,
            metadata=dict(instanceLabel=entry['displayName'],inputMethod='independent-authoring'))))
    ops.extend(dict(op='add_floor_marking',floorMarking=m) for m in markings())
    return ops


def polygon(placement,catalog):
    records = placement_spatial_records(placement,catalog[placement['assetId']])
    assert records
    return unary_union([Polygon(r.polygon) for r in records])


def audit(before,after,catalog):
    expected = apply_facility_layout_operations(before,operations(catalog),updated_at=after['updatedAt'])['document']
    assert after == expected, 'Unexpected changes beyond the three displays and motorcycle pad'
    old = {p['placementId']:p for p in before['placements']}
    new = {p['placementId']:p for p in after['placements']}
    assert new.keys()-old.keys() == {P+k for k in POSES}
    assert all(new[pid] == p for pid,p in old.items())
    routes = [LineString([(p['x'],p['z']) for p in r['centerline']]).buffer(r['corridorWidth']/2,cap_style=2)
              for r in before['routes'] if len(r.get('centerline',[])) > 1]
    bounds = {}
    for key in POSES:
        p = new[P+key]
        shape = polygon(p,catalog)
        bounds[key] = list(shape.bounds)
        assert all(not shape.intersects(route) for route in routes), 'Display blocks a walking route'
        assert shape.disjoint(box(48.5,43,72,52.8)), 'Display obstructs sled lanes or their ends'
        assert shape.disjoint(box(52.5,53.5,70,57.5)), 'Display obstructs tire/hammer stations'
        for pid,existing in old.items():
            if existing['transform']['position']['x'] >= 44 and existing['transform']['position']['z'] >= 40:
                assert shape.distance(polygon(existing,catalog)) > .15, ('Display too close to existing object',key,pid)
        if key == 'ducati':
            assert box(75.8,50.05,80.2,52.95).contains(shape), 'Motorcycle leaves its paved display pad'
        if key == 'dog':
            assert box(68,62,82,72).contains(shape)
        if key == 'bull':
            assert shape.bounds[0] > 46.75 and shape.bounds[1] > 40
    return dict(newPlacements=3,preservedPlacements=len(old),blackGoldPadMarkings=5,
                protectedWalkingRoutes=len(routes),trainingLanesUnchanged=True,
                existingGeometryAndArtworkUnchanged=True,siteNotEnlarged=True,footprints=bounds)


def stage():
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    raw, catalog_raw = target.read_bytes(), manifest.read_bytes()
    before, library = json.loads(raw),json.loads(catalog_raw)
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        file = OUT/name
        if file.exists(): assert file.read_bytes() == data, 'Staging base changed'
        else: file.write_bytes(data)
    entries = [json.loads((ROOT/'generated/industrial_assets/local_library'/('gym-decoration-'+k)/'catalog-entry.json').read_bytes()) for k in POSES]
    assert not {a['assetId'] for a in entries}.intersection(a['assetId'] for a in library['assets'])
    library['assets'].extend(entries)
    library['summary']['total'] = len(library['assets'])
    staged = OUT/'staged-project'
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    validation = OUT/'validation-store'
    for relative in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/relative),_native_fs_path(validation/relative),dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(validation,private_assets=True,private_asset_root=staged)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops = operations(catalog)
        write(OUT/'operations.json',ops)
        candidate = apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks = audit(before,candidate,catalog)
        spatial = host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        candidate = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        audit(before,candidate,catalog)
    finally: host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        assetHashes={e['artifact']:sha(ROOT/e['artifact']) for e in entries},layoutHashes=saved_hashes()))
    fixture = deepcopy(candidate)
    fixture['placements'] = [p for p in candidate['placements'] if p['transform']['position']['x'] >= 44 and p['transform']['position']['z'] >= 40]
    fixture['extensions'].pop('facilityPerimeterWalls',None)
    aids = {p['assetId'] for p in fixture['placements']}
    selected = {a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url='/'+e['artifact'],sourceToCanonical=e['sourceToCanonical']) for a,e in selected.items()}))
    print(json.dumps(checks))


def publish_save():
    report = json.loads((OUT/'report.json').read_bytes())
    proof = json.loads((OUT/'visual-review.json').read_bytes())
    assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    assert target.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed'
    assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes(), 'Library changed'
    for rel,digest in report['assetHashes'].items(): assert sha(ROOT/rel)==digest
    RevisionedAuthorityRepository._atomic_write(manifest,(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes())
    before = json.loads((OUT/'before.json').read_bytes())
    candidate = json.loads((OUT/'candidate.json').read_bytes())
    host = LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        audit(before,candidate,catalog)
        receipt = host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],catalog)
    finally: host.close()
    write(OUT/'saved.json',receipt['layout'])
    hashes = saved_hashes()
    assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report)
    print('saved')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','save'])
    (stage if parser.parse_args().phase=='stage' else publish_save)()
