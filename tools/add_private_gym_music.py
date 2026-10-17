"""Add a wall-mounted music corner and two egg chairs without moving the gym."""
import argparse
from copy import deepcopy
from datetime import datetime,timezone
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools.add_private_gym_decorations import polygon,sha
from tools.add_private_gym_calisthenics import yaw
from tools.build_private_gym import LAYOUT,STORE,write,saved_hashes
from tools.import_private_gym_music import OUT
from shapely.geometry import box
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository,_native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost,PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations

P='pl-gym-music-'
A='asset-gym-music-'
WALL='pl-gym-wellness-lounge-north-left'
KEYS=['piano','guitar-left','guitar-center','guitar-right','egg-chair-left','egg-chair-right']
ENTRIES=[('steinway','catalog-entry.json'),('electric-guitar','catalog-entry.json'),
         ('electric-guitar','catalog-entry-gold.json'),('egg-chair','catalog-entry.json')]


def operations(before,catalog):
    support=next(p for p in before['placements'] if p['placementId']==WALL)
    assert support['transform']['quaternion']==dict(x=0,y=0,z=0,w=1) and support['transform']['scale']==1
    wall=catalog[support['assetId']]['definition']['geometry']['aabb']
    anchor=support['transform']['position']
    inside=anchor['z']+wall['minimum']['z']
    ops=[]
    def place(key,asset,x,z,angle=0,y=0,relationship=None):
        entry=catalog[A+asset]
        ops.append(dict(op='place_asset',placement=dict(placementId=P+key,assetId=entry['assetId'],
            assetDefinitionRevision=entry['assetDefinitionRevision'],positionMode='manual',snapRelationship=relationship,
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=yaw(angle),scale=1),
            metadata=dict(instanceLabel={'piano':'Steinway Upright Piano and Bench',
                'guitar-left':'Wall Guitar - Black Left','guitar-center':'Wall Guitar - Gold Center',
                'guitar-right':'Wall Guitar - Black Right','egg-chair-left':'Music Corner Egg Chair 1',
                'egg-chair-right':'Music Corner Egg Chair 2'}[key],room='lounge',gymRole='amenity',
                inputMethod='independent-authoring',scaleEvidence='Native STEP/IGES unit-converted CAD dimensions'))))
    piano=catalog[A+'steinway']['definition']['geometry']['aabb']
    place('piano','steinway',2.65,inside-.04-piano['maximum']['z'],180)
    for key,asset,x in [('guitar-left','electric-guitar',1.55),('guitar-center','electric-guitar-gold',2.65),
                        ('guitar-right','electric-guitar',3.75)]:
        b=catalog[A+asset]['definition']['geometry']['aabb'];y=1.58
        relation=dict(family='wall_attachment',supportPlacementId=WALL,
            supportAssetDefinitionRevision=support['assetDefinitionRevision'],face='negative_z',
            localX=x-anchor['x'],localY=y-anchor['y'],normalGapMeters=.012)
        place(key,asset,x,inside-.012+b['minimum']['z'],180,y,relation)
    place('egg-chair-left','egg-chair',1.65,-7.2)
    place('egg-chair-right','egg-chair',3.75,-7.2)
    return ops


def audit(before,after,catalog):
    expected=apply_facility_layout_operations(before,operations(before,catalog),updated_at=after['updatedAt'])['document']
    assert after==expected,'Change outside the six approved musical furnishings'
    old={p['placementId']:p for p in before['placements']};new={p['placementId']:p for p in after['placements']}
    assert set(new)-set(old)=={P+k for k in KEYS}
    assert all(new[pid]==p for pid,p in old.items())
    support=old[WALL]
    wall=catalog[support['assetId']]['definition']['geometry']['aabb']
    interior_z=support['transform']['position']['z']+wall['minimum']['z']
    room=box(.24,-17.75,21.90,interior_z-.005)
    through_path=box(5,-17.75,7,-3.1)
    table_tennis_play=box(12.6,-14.8,19.4,-8.8)
    footprints={}
    for key in KEYS:
        p=new[P+key];shape=polygon(p,catalog)
        footprints[key]=list(shape.bounds)
        assert room.contains(shape),'New furniture leaves the entertainment room'
        assert not shape.intersects(through_path),'Main entrance-to-exit path obstructed'
        assert not shape.intersects(table_tennis_play),'Table tennis playing space obstructed'
        b=catalog[p['assetId']]['definition']['geometry']['aabb']
        assert p['transform']['position']['y']+b['maximum']['y']<3.10
        if key.startswith('guitar'):
            assert p['snapRelationship']['supportPlacementId']==WALL
            assert shape.bounds[0]>.3 and shape.bounds[2]<4.9
            assert p['transform']['position']['y']>catalog[A+'steinway']['definition']['geometry']['aabb']['maximum']['y']+.25
            continue
        for existing in old.values():
            pos=existing['transform']['position']
            if not (0<pos['x']<22 and -18<pos['z']<-3.1 and pos['y']==0):continue
            if 'wall' in catalog[existing['assetId']].get('tags',[]):continue
            tags=catalog[existing['assetId']].get('definition',{}).get('tags',[])
            if 'wall' in tags:continue
            assert shape.distance(polygon(existing,catalog))>.25,('Existing furniture clearance',key,existing['placementId'])
    piano_front=footprints['piano'][1]
    assert min(footprints[k][3] for k in ['egg-chair-left','egg-chair-right'])<piano_front-1.2
    assert polygon(new[P+'egg-chair-left'],catalog).distance(polygon(new[P+'egg-chair-right'],catalog))>.7
    return dict(addedPlacements=6,preservedPlacements=len(old),wallMountedGuitars=3,eggChairs=2,
        nativeScalePreserved=True,mainThroughPathWidthMeters=2,existingDoorsArtworkAndGamesUnchanged=True,
        noRoomExpansion=True,footprints=footprints)


def stage():
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST
    raw,original=target.read_bytes(),manifest.read_bytes()
    before,library=json.loads(raw),json.loads(original)
    for name,data in [('before.json',raw),('catalog-before.json',original)]:
        path=OUT/name
        if path.exists():assert path.read_bytes()==data,'Staging base changed'
        else:path.write_bytes(data)
    entries=[json.loads((ROOT/'generated/industrial_assets/local_library'/('gym-music-'+key)/name).read_bytes()) for key,name in ENTRIES]
    assert not {a['assetId'] for a in entries}.intersection(a['assetId'] for a in library['assets'])
    library['assets'].extend(entries);library['summary']['total']=len(library['assets'])
    staged=OUT/'staged-project';write(staged/PRIVATE_ASSET_MANIFEST,library)
    validation=OUT/'validation-store'
    for relative in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/relative),_native_fs_path(validation/relative),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(validation,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops=operations(before,catalog);write(OUT/'operations.json',ops)
        candidate=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks=audit(before,candidate,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        candidate=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))['layout']
        audit(before,candidate,catalog)
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,
        assetHashes={e['artifact']:sha(ROOT/e['artifact']) for e in entries},layoutHashes=saved_hashes()))
    fixture=deepcopy(candidate)
    fixture['placements']=[p for p in candidate['placements'] if 0<=p['transform']['position']['x']<=22 and -18<=p['transform']['position']['z']<=-3]
    fixture['extensions'].pop('facilityPerimeterWalls',None)
    aids={p['assetId'] for p in fixture['placements']}
    selected={a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json',dict(layout=fixture,catalog=[catalog[a] for a in sorted(aids)],
        artifacts={a:dict(url='/'+e['artifact'],sourceToCanonical=e['sourceToCanonical']) for a,e in selected.items()}))
    print(json.dumps(checks),flush=True)


def save():
    report=json.loads((OUT/'report.json').read_bytes())
    for name in ['visual-review.json','browser-check.json']:
        proof=json.loads((OUT/name).read_bytes())
        assert proof['status']=='passed' and proof['candidateSha256']==sha(OUT/'candidate.json')
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST
    assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
    assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes(),'Library changed'
    for rel,digest in report['assetHashes'].items():assert sha(ROOT/rel)==digest
    RevisionedAuthorityRepository._atomic_write(manifest,(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes())
    before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads((OUT/'candidate.json').read_bytes())
    host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        audit(before,candidate,catalog)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        audit(before,receipt['layout'],catalog)
    finally:host.close()
    write(OUT/'saved.json',receipt['layout'])
    hashes=saved_hashes()
    assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
    report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
    write(OUT/'report.json',report);print('saved',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=['stage','save'])
    stage() if parser.parse_args().phase=='stage' else save()
