"""Relocate the outdoor support wall and install three matching exercise stations."""
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

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),
    str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'),
    str(ROOT/'.runtime/model-import-20261002/mesh-dependencies')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import canonicalize_quaternion, layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.spatial import placement_spatial_records
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT=ROOT/'.runtime/private-gym-calisthenics-20261009'
A='asset-gym-calisthenics-'
P='pl-gym-calisthenics-'
WALL='pl-private-gym-fields-training-support'
OLD_RACK='pl-private-gym-fields-wall-mounted-rack'
PAD='fm-private-gym-fields-rack-pad'
KINDS=['wall-bar','pushup-supports']


def yaw(degrees):
    angle=math.radians(degrees)/2
    return canonicalize_quaternion(dict(x=0,y=math.sin(angle),z=0,w=math.cos(angle)))


def operations(before,catalog):
    wall=next(p for p in before['placements'] if p['placementId']==WALL)
    ops=[dict(op='delete_placement',placementId=OLD_RACK),
        dict(op='move_placement',placementId=WALL,position=dict(x=44.2,y=0,z=67)),
        dict(op='rotate_placement',placementId=WALL,quaternion=yaw(270)),
        dict(op='edit_floor_marking',markingId=PAD,patch=dict(
            transform=dict(position=dict(x=47.4,y=.003,z=67),rotationDegrees=270)))]
    for index,local_x in enumerate([-2.5,0,2.5],1):
        for kind in KINDS:
            asset=catalog[A+kind]
            mounted=kind=='wall-bar'
            # The wall's negative-Z face now points +X toward the patio.
            bounds=asset['definition']['geometry']['aabb']
            x=round(44.2+.125+.01-bounds['minimum']['z'],6) if mounted else 45.8
            attachment=dict(family='wall_attachment',supportPlacementId=WALL,
                supportAssetDefinitionRevision=wall['assetDefinitionRevision'],face='negative_z',
                localX=local_x,localY=0,normalGapMeters=.01) if mounted else None
            placement=dict(placementId=P+kind+'-'+str(index),assetId=A+kind,
                assetDefinitionRevision=asset['assetDefinitionRevision'],positionMode='manual',
                transform=dict(position=dict(x=x,y=0,z=67+local_x),quaternion=yaw(90 if mounted else 0),scale=1),
                snapRelationship=attachment,metadata=dict(inputMethod='independent-authoring',
                    instanceLabel=('Gold Wall Station ' if mounted else 'Push-Up Support Pair ')+str(index)))
            ops.append(dict(op='place_asset',placement=placement))
    return ops


def audit(before,after,catalog):
    old={p['placementId']:p for p in before['placements']}
    new={p['placementId']:p for p in after['placements']}
    expected={P+k+'-'+str(i) for k in KINDS for i in range(1,4)}
    assert old.keys()-new.keys()=={OLD_RACK}, 'Unexpected removed equipment'
    assert new.keys()-old.keys()==expected, 'Missing or extra station'
    assert all(new.get(pid)==p for pid,p in old.items() if pid not in {WALL,OLD_RACK}), 'Unrelated placement changed'
    wall=deepcopy(old[WALL])
    wall['transform']['position']=dict(x=44.2,y=0,z=67)
    wall['transform']['quaternion']=yaw(270)
    assert new[WALL]==wall, 'Wall identity, geometry or finish changed'
    for key,value in before.items():
        if key not in {'placements','floorMarkings','updatedAt'}:
            assert after[key]==value, ('Unrelated layout change',key)
    expected_markings=deepcopy(before['floorMarkings'])
    next(m for m in expected_markings if m['markingId']==PAD)['transform']=dict(
        position=dict(x=47.4,y=.003,z=67),rotationDegrees=270)
    assert after['floorMarkings']==expected_markings, 'Unrelated marking changed'
    for op in operations(before,catalog):
        if op['op']=='place_asset':
            p=op['placement']
            assert new[p['placementId']]==p, 'Station pose or attachment changed'
    for pid in expected|{WALL}:
        p=new[pid]
        for bounds in placement_spatial_records(p,catalog[p['assetId']]):
            assert abs(bounds.minimum_y)<1e-6, 'Equipment does not meet ground'
            assert all(44<=x<=50.4 and 62.5<=z<=71.5 for x,z in bounds.polygon), 'Outside corner exercise area'
            if p['assetId']==A+'wall-bar':
                assert 2.55<bounds.maximum_y<2.56
            if p['assetId']==A+'pushup-supports':
                assert .43<bounds.maximum_y<.44
    for kind,width in [('wall-bar',1.34216833),('pushup-supports',.66)]:
        bounds=catalog[A+kind]['definition']['geometry']['aabb']
        assert abs(bounds['maximum']['x']-bounds['minimum']['x']-width)<1e-5
    return dict(matchingWallStations=3,pushupPairs=3,individualPushupSupports=6,
        wallFacing='+X toward barbecue patio',wallMoved=True,padMoved=True,
        originalPlacementsPreserved=len(old)-2,patioAndRemainingLayoutUnchanged=True,nativeScalePreserved=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish-assets','save'])
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest,staged=ROOT/PRIVATE_ASSET_MANIFEST,OUT/'staged-project'
    if args.phase!='stage':
        report=json.loads((OUT/'report.json').read_text())
        assert target.read_bytes()==(OUT/'before.json').read_bytes(), 'Saved gym changed'
        if args.phase=='publish-assets':
            assert report['status']=='validated'
            assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes(), 'Catalog changed'
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
            finally:
                host.close()
            write(OUT/'saved.json',receipt['layout'])
            report.update(status='saved',savedRevision=receipt['revision'])
            hashes=saved_hashes()
            assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged']=True
        write(OUT/'report.json',report)
        print(report['status'])
        return
    raw,catalog_raw=target.read_bytes(),manifest.read_bytes()
    before,library=json.loads(raw),json.loads(catalog_raw)
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        file=OUT/name
        if file.exists():
            assert file.read_bytes()==data, 'Base changed'
        else:
            file.write_bytes(data)
    entries=[json.loads((ROOT/'generated/industrial_assets/local_library'/('gym-calisthenics-'+k)/'catalog-entry.json').read_text()) for k in KINDS]
    assert not {e['assetId'] for e in entries}.intersection(e['assetId'] for e in library['assets'])
    library['assets'].extend(entries)
    library['summary']['total']=len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops=operations(before,catalog)
        write(OUT/'operations.json',ops)
        candidate=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks=audit(before,candidate,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally:
        host.close()
    write(OUT/'candidate.json',receipt['layout'])
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),layoutHashes=saved_hashes(),checks=checks,
        assetHashes={e['artifact']:hashlib.sha256((ROOT/e['artifact']).read_bytes()).hexdigest() for e in entries},
        limitations=['Concept arrangement; wall strength, fixings, exercise clearance and load ratings require independent review.']))
    profile=json.loads((ROOT/'.runtime/private-gym-conditioning-20261009/profile.json').read_text())
    profile.update(profileId='private-gym-calisthenics',origin='http://127.0.0.1:8569',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,cameraFov=50,
        requiredAssets=[A+k for k in KINDS],shots=[
            shot('01-stations-facing-patio',(55,4,67),(44.8,1.3,67)),
            shot('02-pushup-supports',(49,2.5,64.7),(45.3,.8,64.5)),
            shot('03-corner-and-patio',(86,31,89),(61,0,61)),
            shot('04-wall-attachment',(46,2.5,62),(44.5,1.5,64.5))],
        finalShot=shot('05-saved-outdoor-area',(81,25,87),(60,0,61))))
    print(json.dumps(checks))


if __name__=='__main__':
    main()
