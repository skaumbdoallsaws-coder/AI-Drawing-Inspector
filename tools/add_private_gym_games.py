"""Stage and validate games-room additions and an attached office Bible."""
import argparse
from copy import deepcopy
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from tools.import_private_gym_games import OUT, base
from tools.apex_equipment_materials import np, trimesh
from shapely.geometry import box, Polygon
from shapely.ops import unary_union
from tools.add_private_gym_decorations import polygon, sha
from tools.build_private_gym import STORE, LAYOUT, write, saved_hashes
from tools.equip_factory02_cubicles import transform
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision, canonicalize_layout
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

PREFIX = 'asset-gym-games-'
P = 'pl-gym-games-'
TV = 'pl-gym-gaming-complete-tv-unit'
SEATING = 'pl-gym-gaming-living-room-1'
DESK = 'pl-gym-office-desk-and-three-chairs'
CABINET = 'pl-gym-wellness-lounge-display-cabinet'
ARCADE = 'pl-gym-wellness-arcade'
KEYS = ['pool', 'ps5', 'controller', 'bible', 'arcade-small']
CHANGED = {TV, SEATING, CABINET, ARCADE}
ADDED = {P+k for k in ['pool', 'ps5', 'controller-1', 'controller-2', 'bible', 'arcade']}


def surface(sid, label, x0, x1, z0, z1, y):
    return dict(surfaceId=sid, label=label, localFrame=dict(origin=dict(x=0,y=y,z=0),
        normal=dict(x=0,y=1,z=0), xAxis=dict(x=1,y=0,z=0), zAxis=dict(x=0,y=0,z=1)),
        bounds=dict(minimumX=x0,maximumX=x1,minimumZ=z0,maximumZ=z1),
        allowedSides=['above'], evidenceStatus='derived')


def horizontal_geometry(entry, y):
    scene = trimesh.load_scene(ROOT/entry['artifact'], process=False)
    matrix = np.array(entry['sourceToCanonical']).reshape(4,4).T
    pieces = []
    for node in scene.graph.nodes_geometry:
        m, name = scene.graph[node]
        mesh = scene.geometry[name].copy();mesh.apply_transform(matrix@m)
        ids = np.flatnonzero((mesh.face_normals[:,1]>.9999)&(np.abs(mesh.triangles_center[:,1]-y)<.00001))
        pieces.extend(Polygon(t[:,[0,2]]) for t in mesh.triangles[ids])
    return unary_union(pieces).buffer(.000001)


def assets(library):
    entries = [json.loads((base.LIBRARY/('gym-games-'+k)/'catalog-entry.json').read_bytes()) for k in KEYS]
    variants = [
        ('asset-gym-additional-tv-unit-gold-bezel', 'tv-support', surface('console-shelf', 'Measured TV side shelf', -1.445, -1.145, -.25, .21, .7953953146934509)),
        ('asset-gym-living-room-1', 'seating-support', surface('coffee-table', 'Measured round coffee table inset', -.39, .41, .49, 1.29, .506798505783081)),
    ]
    for old, key, s in variants:
        original = next(a for a in library['assets'] if a['assetId']==old)
        entry = deepcopy(original)
        entry.update(assetId=PREFIX+key, supportSurfaces=[s])
        entry['source']['supportedVariantOf'] = old
        entry['displayName'] += ' - Measured Accessory Support'
        b=s['bounds'];region=box(b['minimumX'],b['minimumZ'],b['maximumX'],b['maximumZ'])
        assert horizontal_geometry(original,s['localFrame']['origin']['y']).covers(region), ('Support not on CAD surface', key)
        entries.append(entry)
    assert not {e['assetId'] for e in entries}.intersection(e['assetId'] for e in library['assets'])
    library['assets'].extend(entries);library['summary']['total']=len(library['assets'])
    return entries


def change(before, catalog):
    result=deepcopy(before);ps={p['placementId']:p for p in result['placements']}
    for pid,key in [(TV,'tv-support'),(SEATING,'seating-support')]:
        ps[pid].update({k:catalog[PREFIX+key][k] for k in ('assetId','assetDefinitionRevision')})
    identity=dict(transform=dict(position=dict(x=0,y=0,z=0),quaternion=dict(x=0,y=0,z=0,w=1),scale=1))
    ps[CABINET]['transform']=transform(identity,11.6,-3.58,180,0)
    ps[ARCADE]['transform']=transform(identity,13,-17.0,0,0)
    def place(key, aid, x, z, yaw=0):
        p=dict(placementId=P+key, assetId=aid, assetDefinitionRevision=catalog[aid]['assetDefinitionRevision'],
            transform=transform(identity,x,z,yaw,0), positionMode='manual', snapRelationship=None,
            metadata=dict(instanceLabel=key.replace('-',' ').title(),inputMethod='independent-authoring'))
        result['placements'].append(p);ps[p['placementId']]=p
        return p
    def attach(key, aid, parent, sid, x, z, yaw=0):
        p=place(key,aid,0,0);support=ps[parent]
        s=next(s for s in catalog[support['assetId']]['supportSurfaces'] if s['surfaceId']==sid)
        p['transform']=transform(support,x,z,yaw,s['localFrame']['origin']['y'])
        p['snapRelationship']=dict(family='surface_attachment',attachmentId='surface:'+p['placementId'],
            supportPlacementId=parent,surfaceId=sid,surfaceSource='asset_definition',localPosition=dict(x=x,z=z),
            localRotationDegrees=yaw,normalOffsetMeters=0,side='above',evidenceStatus='derived')
        return p
    place('pool',PREFIX+'pool',2.65,-11.5,90)['metadata']['instanceLabel']='APEX Pool Table'
    place('arcade',PREFIX+'arcade-small',15,-17.0)['metadata']['instanceLabel']='APEX Arcade Cabinet'
    attach('ps5',PREFIX+'ps5',TV,'console-shelf',-1.295,-.02)['metadata']['instanceLabel']='PlayStation 5 Pro'
    attach('controller-1',PREFIX+'controller',SEATING,'coffee-table',-.20,.89,172)
    attach('controller-2',PREFIX+'controller',SEATING,'coffee-table',.23,.89,188)
    attach('bible',PREFIX+'bible',DESK,'worktop',-.58,.12,0)['metadata']['instanceLabel']='Holy Bible'
    return canonicalize_layout(result)


def audit(before, after, catalog):
    expected=change(before,catalog);expected['updatedAt']=after['updatedAt']
    assert after==expected,'Unexpected edits beyond the scoped additions and room rearrangement'
    old={p['placementId']:p for p in before['placements']};ps={p['placementId']:p for p in after['placements']}
    assert set(ps)-set(old)==ADDED and set(old)<=set(ps)
    assert all(old[k]==ps[k] for k in old if k not in CHANGED)
    for pid in (TV,SEATING):
        a,b=deepcopy(old[pid]),deepcopy(ps[pid])
        for key in ('assetId','assetDefinitionRevision'):a.pop(key);b.pop(key)
        assert a==b
    pool=polygon(ps[P+'pool'],catalog);cue=pool.envelope.buffer(1.45,join_style=2)
    assert box(.25,-17.75,4.99,-3.1).contains(cue)
    main=box(5,-17.75,7,-3.1);table_tennis=box(12.6,-14.8,19.4,-8.8)
    arcade_stance=box(12.25,-16.43,15.65,-14.85)
    for p in after['placements']:
        if p['transform']['position']['y']>1.4:continue
        footprint=polygon(p,catalog)
        assert main.intersection(footprint).area<1e-6,('Main walkway blocked',p['placementId'])
        if p['placementId']!=P+'pool':assert cue.intersection(footprint).area<1e-6,('Pool cue space blocked',p['placementId'])
        if p['placementId'] in {P+'arcade',ARCADE,CABINET,P+'pool'}:
            assert table_tennis.intersection(footprint).area<1e-6
        if p['placementId'] not in {ARCADE,P+'arcade'}:
            assert arcade_stance.intersection(footprint).area<1e-6,('Arcade approach blocked',p['placementId'])
    attachments=[]
    for pid in ADDED:
        p=ps[pid];assert p['transform']['scale']==1
        r=p.get('snapRelationship')
        if not r:continue
        parent=ps[r['supportPlacementId']]
        s=next(s for s in catalog[parent['assetId']]['supportSurfaces'] if s['surfaceId']==r['surfaceId'])
        local=deepcopy(p);local['transform']=transform(dict(transform=dict(position=dict(x=0,y=0,z=0),quaternion=dict(x=0,y=0,z=0,w=1),scale=1)),r['localPosition']['x'],r['localPosition']['z'],r['localRotationDegrees'],0)
        b=s['bounds'];o=s['localFrame']['origin'];region=box(b['minimumX']+o['x'],b['minimumZ']+o['z'],b['maximumX']+o['x'],b['maximumZ']+o['z'])
        assert region.contains(polygon(local,catalog)),('Accessory leaves support',pid)
        assert abs(p['transform']['position']['y']-(parent['transform']['position']['y']+o['y']))<1e-6
        for other in after['placements']:
            rr=other.get('snapRelationship') or {}
            if other['placementId']!=pid and rr.get('supportPlacementId')==parent['placementId'] and rr.get('family')=='surface_attachment':
                assert polygon(p,catalog).distance(polygon(other,catalog))>.02,(pid,other['placementId'])
        attachments.append(dict(placementId=pid,support=parent['placementId'],surfaceId=r['surfaceId'],height=p['transform']['position']['y']))
    return dict(addedPlacements=sorted(ADDED),preservedPlacements=len(old)-len(CHANGED),cueClearanceMeters=1.45,
        poolFootprint=list(pool.bounds),cueEnvelope=list(cue.bounds),mainWalkwayMeters=2,attachments=attachments,
        movedFurniture=[CABINET,ARCADE],additionalArcades=1,unchangedGeometryArtAndOtherRooms=True)


def stage():
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST
    raw,original=target.read_bytes(),manifest.read_bytes();before,library=json.loads(raw),json.loads(original)
    for name,data in [('before.json',raw),('catalog-before.json',original)]:
        path=OUT/name
        if path.exists():assert path.read_bytes()==data,'Staging base changed'
        else:path.write_bytes(data)
    entries=assets(library);staged=OUT/'staged-project';write(staged/PRIVATE_ASSET_MANIFEST,library)
    store=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:copytree(_native_fs_path(STORE/rel),_native_fs_path(store/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(store,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        candidate=change(before,catalog);checks=audit(before,candidate,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        audit(before,candidate,catalog)
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        assetHashes={e['artifact']:sha(ROOT/e['artifact']) for e in entries},layoutHashes=saved_hashes(),
        notes=['Controller CAD contains PS4-style geometry despite its PS5 filename; compatibility is not claimed.',
            'Kombie arcade excluded because two source faces fail tessellation. Cue clearance is a geometric planning allowance, not a standards certification.']))
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if 0<=p['transform']['position']['x']<=36 and -18<=p['transform']['position']['z']<=-3 and (p['transform']['position']['x']<=22 or (p['transform']['position']['x']>=30 and p['transform']['position']['z']>=-11))]
    aids={p['assetId'] for p in fixture['placements']};byid={a['assetId']:a for a in library['assets']}
    finish=fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    pids={p['placementId'] for p in fixture['placements']}
    finish['fittedArtworks']=[a for a in finish.get('fittedArtworks',[]) if a.get('target',{}).get('placementId') in pids]
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url='/'+byid[a]['artifact'],sourceToCanonical=byid[a]['sourceToCanonical']) for a in aids}))
    print(json.dumps(checks),flush=True)


def save():
    report=json.loads((OUT/'report.json').read_bytes())
    for name in ['visual-review.json','browser-check.json']:
        proof=json.loads((OUT/name).read_bytes());assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST
    assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes(),'Library changed'
    for rel,digest in report['assetHashes'].items():assert sha(ROOT/rel)==digest
    RevisionedAuthorityRepository._atomic_write(manifest,(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes())
    host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
        audit(before,candidate,catalog)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],catalog)
    finally:host.close()
    write(OUT/'saved.json',receipt['layout']);hashes=saved_hashes()
    assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report);print('saved',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=['stage','save'])
    stage() if parser.parse_args().phase=='stage' else save()
