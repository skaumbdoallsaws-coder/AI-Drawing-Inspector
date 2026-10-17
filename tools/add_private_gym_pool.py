"""Stage a measured pool/spa annex; save only the native-desktop-verified candidate."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
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
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write, saved_hashes
from tools.private_gym_reception_art import wall_glb
from tools.add_factory02_conference_rooms import box_glb
from tools.audit_independent_factory_layer2 import footprint
from tools.apex_equipment_materials import unpack, pack

OUT = ROOT / '.runtime/private-gym-pool-20261008'
P = 'pl-gym-pool-'
Z = 'zn-gym-pool-'
POOL = 'asset-gym-pool-concept-1-installed'
SPA = 'asset-gym-pool-jacuzzi-installed'
OLD_WALL = 'pl-gym-wellness-annex-east'
POOL_X, POOL_Z, DECK_HEIGHT = 41.5, -10.0, 1.75
POOL_RECT = (38.525, -13.925, 44.475, -6.075)
ANNEX = (36.0, -18.0, 50.0, 0.0)


def walls():
    # Separate physical segments leave a real 1.8 m corridor opening, not a visual-only hole.
    return [
        ('connection-south', .228, 15.374, 3.2, 35.88, -10.187),
        ('connection-north', .228, .568, 3.2, 35.88, -.416),
        ('east-wall', .228, 17.604, 3.2, 49.88, -8.934),
        ('front-wall', 13.72, .228, 3.2, 42.88, -17.88),
    ]


def prepare_assets(library):
    staged = OUT / 'staged-project'
    artifacts, entries = [], []
    def emit(key, raw):
        rel = f'generated/industrial_assets/private_gym/pool/{key}-{hashlib.sha256(raw).hexdigest()[:16]}.glb'
        path = staged / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        artifacts.append(rel)
        return rel
    for key in ['concept-1', 'concept-2', 'jacuzzi']:
        entry = json.loads((ROOT / f'generated/industrial_assets/local_library/gym-pool-{key}/catalog-entry.json').read_text())
        entries.append(entry)
        if key == 'concept-2':
            continue
        variant = deepcopy(entry)
        raw = (ROOT / entry['artifact']).read_bytes()
        doc, data = unpack(raw)
        for mat in doc.get('materials', []):
            mat.setdefault('extras', {})['facilityAuthoredFinish'] = True
            pbr = mat.setdefault('pbrMetallicRoughness', {})
            pbr.setdefault('roughnessFactor', .55)
        variant.update(assetId=POOL if key == 'concept-1' else SPA,
            displayName=entry['displayName'] + ' - Source Finishes', artifact=emit(key, pack(doc, data)))
        variant['source']['appearanceVariantOf'] = entry['assetId']
        entries.append(variant)
    logo = (ROOT / 'generated/industrial_assets/private_gym/apex-court/back/branding-only/centered/apex-logo.png').read_bytes()
    for key, w, d, h, _, _ in walls():
        dims = dict(width=w, depth=d, height=h)
        raw = wall_glb(logo, dims, fit='contain', face=1, name='APEX Pool and Spa') if key == 'front-wall' else box_glb(w, d, h)
        entries.append(dict(assetId='asset-gym-pool-' + key, displayName='APEX Pool ' + key.replace('-', ' ').title(),
            category='Building Structures', artifact=emit(key, raw), dimensions=dims, sourceToCanonical=IDENTITY,
            description='Concept pool-room partition. Building and wet-area compliance are not qualified.',
            tags=['wall', 'gym', 'pool'], source=dict(kind='authored-primitive', generator=Path(__file__).name)))
    assert not {e['assetId'] for e in entries}.intersection(e['assetId'] for e in library['assets'])
    library['assets'].extend(entries)
    library['summary']['total'] = len(library['assets'])
    write(staged / PRIVATE_ASSET_MANIFEST, library)
    return artifacts, {e['artifact'] for e in entries}


def ground_surfaces():
    x0, z0, x1, z1 = ANNEX
    a, b, c, d = POOL_RECT
    regions = [('west', (x0, z0, a, z1), 0), ('east', (c, z0, x1, z1), 0),
        ('south', (a, z0, c, b), 0), ('north', (a, d, c, z1), 0),
        ('basin', POOL_RECT, -DECK_HEIGHT)]
    return [dict(surfaceId='gym-pool-' + key, minX=a, maxX=c, minZ=b, maxZ=d,
        startElevation=y, endElevation=y, slopeAxis='x', color='#59636A' if y == 0 else '#35393E')
        for key, (a, b, c, d), y in regions]


def operations(before, catalog):
    ground = deepcopy(before['extensions']['facilityGround'])
    ground['surfaces'].extend(ground_surfaces())
    ops = [dict(op='set_ground', ground=ground), dict(op='delete_placement', placementId=OLD_WALL)]
    def zone(key, label, bounds, elevation=0):
        a, b, c, d = bounds
        ops.append(dict(op='add_zone', zone=dict(zoneId=Z+key, label=label, zoneType='workcell',
            boundary=[dict(x=a,z=b),dict(x=c,z=b),dict(x=c,z=d),dict(x=a,z=d)], floorElevation=elevation,
            anchors=[], evidence=[], extensions=dict(style=dict(fillColor='#59636A')))))
    zone('annex', 'APEX Pool + Spa', ANNEX)
    zone('recess', 'Recessed Pool Assembly', POOL_RECT, -DECK_HEIGHT)
    def place(key, asset, x, z, y=0, yaw=0, color=None):
        q = math.radians(yaw)/2
        p = dict(placementId=P+key, assetId=asset, assetDefinitionRevision=catalog[asset]['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1),
            positionMode='manual', snapRelationship=None, metadata=dict(instanceLabel=key.replace('-', ' ').title(),
                room='pool-and-spa', inputMethod='independent-authoring'))
        if color:
            p['appearance'] = dict(color=color)
        ops.append(dict(op='place_asset', placement=p))
    for key, w, d, h, x, z in walls():
        place(key, 'asset-gym-pool-'+key, x, z, color='#3B4147')
    place('swimming-pool', POOL, POOL_X, POOL_Z, y=-DECK_HEIGHT)
    place('corner-jacuzzi', SPA, 48.8, -16.55, yaw=180)
    place('towel-storage', 'asset-hideaway-cabinet', 37.05, -3.6, yaw=90, color='#17191C')
    for key, z in [('relax-chair-1', -8.1), ('relax-chair-2', -10.5)]:
        place(key, 'asset-chair-black', 48.3, z, yaw=270, color='#35393E')
    place('side-table', 'asset-gym-wellness-coffee-table', 48.3, -9.3, yaw=90, color='#C99B39')
    def mark(key, bounds, text=''):
        a,b,c,d = bounds
        ops.append(dict(op='add_floor_marking', floorMarking=dict(markingId='fm-gym-pool-'+key,
            label=key.replace('-', ' ').title(), markingType='floor_text' if text else 'solid_line',
            semanticRole='decorative', positionMode='manual', transform=dict(position=dict(x=(a+c)/2,y=.014,z=(b+d)/2),rotationDegrees=0),
            width=c-a, depth=d-b, fillColor='#C99B39', strokeColor='#C99B39', opacity=1, text=text, evidence=[], metadata={})))
    mark('arrival', (38.2,-2.5,44.8,-1.9), 'APEX | POOL + SPA')
    mark('west-accent',(36.4,-17.35,36.45,-5.5))
    mark('front-accent',(36.4,-17.35,49.3,-17.30))
    mark('east-accent',(49.3,-15,49.35,-3))
    return ops


def audit(before, after, catalog):
    from shapely.geometry import box, LineString
    original = {p['placementId']:p for p in before['placements']}
    actual = {p['placementId']:p for p in after['placements']}
    assert OLD_WALL in original and OLD_WALL not in actual
    expected = {P + key for key in ['swimming-pool','corner-jacuzzi','towel-storage',
        'relax-chair-1','relax-chair-2','side-table'] + [w[0] for w in walls()]}
    assert actual.keys() - original.keys() == expected, 'Unexpected added placement'
    for pid, p in original.items():
        if pid != OLD_WALL:
            assert actual[pid] == p, ('Unexpected placement change', pid)
    assert after['extensions']['facilityPerimeterWalls'] == before['extensions']['facilityPerimeterWalls']
    assert after['zones'][:len(before['zones'])] == before['zones']
    assert after['floorMarkings'][:len(before['floorMarkings'])] == before['floorMarkings']
    for key, value in before.items():
        if key not in {'placements','zones','floorMarkings','extensions','updatedAt'}:
            assert after[key] == value, ('Unexpected layout change', key)
    for key, value in before['extensions'].items():
        if key != 'facilityGround':
            assert after['extensions'][key] == value
    old_ground = before['extensions']['facilityGround']['surfaces']
    assert after['extensions']['facilityGround']['surfaces'][:len(old_ground)] == old_ground
    assert after['extensions']['facilityGround']['surfaces'][len(old_ground):] == ground_surfaces()
    assert actual[P+'swimming-pool']['transform']['position']['y'] == -DECK_HEIGHT
    assert actual[P+'swimming-pool']['transform']['scale'] == 1
    assert actual[P+'corner-jacuzzi']['transform']['scale'] == 1
    shape = footprint(actual[P+'swimming-pool'], catalog[POOL])
    assert shape.symmetric_difference(box(*POOL_RECT)).area < 1e-4
    surfaces = ground_surfaces()
    polygons = [box(s['minX'],s['minZ'],s['maxX'],s['maxZ']) for s in surfaces]
    assert abs(sum(p.area for p in polygons)-box(*ANNEX).area) < 1e-7
    for i, p in enumerate(polygons):
        for other in polygons[i+1:]:
            assert p.intersection(other).area < 1e-8
    # Independently check a clear 1.2 m route through the connecting door and around the pool.
    paths = [[(34.8,-1.6),(46.2,-1.6),(46.2,-15),(37.3,-15),(37.3,-5.3),(41.5,-5.3)]]
    for points in paths:
        clearance = LineString(points).buffer(.6, cap_style=2, join_style=2)
        for p in actual.values():
            if p['transform']['position']['y'] > 1:
                continue
            assert clearance.intersection(footprint(p,catalog[p['assetId']])).area < 1e-7, ('Blocked pool circulation',p['placementId'])
    return dict(annexMeters=[14,18], poolDeckMeters=[5.95,7.85], poolRecessMeters=DECK_HEIGHT,
        compactJacuzziMeters=[1.5,1.5], nativeScalePreserved=True, existingRoomsPreserved=True,
        doorwayMeters=1.8, checkedCirculationWidthMeters=1.2, poolDeckFlushWithRoomFloor=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage','publish-assets','save'])
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    staged=OUT/'staged-project'
    if args.phase!='stage':
        report=json.loads((OUT/'report.json').read_text())
        assert target.read_bytes()==(OUT/'before.json').read_bytes(), 'Saved gym changed'
        if args.phase=='publish-assets':
            assert report['status']=='validated' and manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes()
            for rel in report['artifacts']:
                dest=ROOT/rel
                payload=(staged/rel).read_bytes()
                if dest.exists(): assert dest.read_bytes()==payload
                else: RevisionedAuthorityRepository._atomic_write(dest,payload)
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            assert report['status']=='assets-published'
            raw=(OUT/'candidate.json').read_bytes()
            proof=json.loads((OUT/'native-check.json').read_text())
            assert proof['status']=='preview-verified' and proof['candidateHash']==hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for rel,digest in report['assetHashes'].items():
                assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
                audit(json.loads((OUT/'before.json').read_bytes()),json.loads(raw),catalog)
                receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,json.loads(raw),report['baseRevision'])
            finally: host.close()
            write(OUT/'saved.json',receipt['layout'])
            report.update(status='saved',savedRevision=receipt['revision'])
            hashes=saved_hashes()
            assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged']=True
        write(OUT/'report.json',report)
        print(report['status'])
        return
    raw=target.read_bytes()
    before=json.loads(raw)
    catalog_raw=manifest.read_bytes()
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        path=OUT/name
        if path.exists(): assert path.read_bytes()==data, 'Base changed'
        else: path.write_bytes(data)
    library=json.loads(catalog_raw)
    artifacts,imported=prepare_assets(library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops=operations(before,catalog)
        write(OUT/'operations.json',ops)
        candidate=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        write(OUT/'candidate-draft.json',candidate)
        checks=audit(before,candidate,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally: host.close()
    write(OUT/'candidate.json',receipt['layout'])
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),layoutHashes=saved_hashes(),
        artifacts=artifacts,assetHashes={rel:hashlib.sha256(((staged if rel in artifacts else ROOT)/rel).read_bytes()).hexdigest() for rel in imported},
        checks=checks,limitations=['Concept layout only; pool structure, waterproofing, treatment, ventilation, accessible entry and building compliance are unqualified.',
            'Jacuzzi is the supplied 1500 mm corner bath, not a multi-person commercial spa.',
            'Pool assembly collision envelope conservatively includes its integrated deck and loungers.']))
    profile=json.loads((ROOT/'.runtime/private-gym-office-20261008/profile.json').read_text())
    profile.update(profileId='private-gym-pool',origin='http://127.0.0.1:8563',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    front=shot('01-pool-from-entry',(38,2.5,-2.6),(43,.3,-11))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,requiredAssets=[POOL,SPA],
        shots=[front,shot('02-pool-overhead',(43,24,-8),(43,0,-9)),
            shot('03-jacuzzi',(46.5,1.9,-13.8),(48.8,.35,-16.55)),
            shot('04-pool-deck',(46.6,1.8,-10.6),(41.5,-.15,-10)),
            shot('05-annex-connection',(33.8,1.65,-1.6),(41,1,-1.6))],
        finalShot=shot('06-saved-pool',(46.8,4,-3.5),(42,.3,-11))))
    print(json.dumps(checks))


if __name__=='__main__':
    main()
