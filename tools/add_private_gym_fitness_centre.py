"""Replace outdoor strength equipment and place the decorative wagon.

The requested weights are pending a correct source; assembly.STEP contains a car.
"""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),
    str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'),
    str(ROOT/'.runtime/model-import-20261002/mesh-dependencies')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.spatial import placement_spatial_records
from tools.add_private_gym_calisthenics import yaw
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT=ROOT/'.runtime/private-gym-fitness-centre-20261009'
A='asset-gym-fitness-centre-'
P='pl-gym-fitness-centre-'
KINDS=['centre','wagon']
REMOVED={'pl-private-gym-fields-'+k for k in ['pull-up-station','free-weight-bench','dumbbell-storage']}
PAD='fm-private-gym-fields-strength-pad'
PAD_PATCH=dict(label='Calisthenics Fitness Centre Pad')


def operations(before,catalog):
    existing={p['placementId']:p for p in before['placements']}
    assert REMOVED.issubset(existing), 'Expected strength equipment is missing'
    assert any(m['markingId']==PAD for m in before['floorMarkings']), 'Strength pad missing'
    poses={'centre':(61,68.1,90),'wagon':(78.3,57.1,270)}
    ops=[dict(op='delete_placement',placementId=pid) for pid in sorted(REMOVED)]
    ops.append(dict(op='edit_floor_marking',markingId=PAD,patch=deepcopy(PAD_PATCH)))
    for kind in KINDS:
        x,z,angle=poses[kind]
        ops.append(dict(op='place_asset',placement=dict(placementId=P+kind,assetId=A+kind,
            assetDefinitionRevision=catalog[A+kind]['assetDefinitionRevision'],positionMode='manual',
            transform=dict(position=dict(x=x,y=0,z=z),quaternion=yaw(angle),scale=1),snapRelationship=None,
            metadata=dict(instanceLabel={'centre':'Calisthenics Fitness Centre',
                'wagon':'Decorative Western Wagon'}[kind],inputMethod='independent-authoring'))))
    return ops


def footprint(placement,catalog):
    records=placement_spatial_records(placement,catalog[placement['assetId']])
    assert records
    xs=[x for r in records for x,z in r.polygon]
    zs=[z for r in records for x,z in r.polygon]
    assert all(abs(r.minimum_y)<1e-6 for r in records), 'New asset is not on the ground'
    return min(xs),min(zs),max(xs),max(zs)


def audit(before,after,catalog):
    old={p['placementId']:p for p in before['placements']}
    new={p['placementId']:p for p in after['placements']}
    assert old.keys()-new.keys()==REMOVED, 'Unexpected equipment removed'
    assert new.keys()-old.keys()=={P+k for k in KINDS}, 'New model missing or duplicated'
    assert all(new[pid]==p for pid,p in old.items() if pid not in REMOVED), 'Unrelated placement changed'
    for key,value in before.items():
        if key not in {'placements','floorMarkings','updatedAt'}:
            assert after[key]==value, ('Unrelated change',key)
    expected_markings=deepcopy(before['floorMarkings'])
    next(m for m in expected_markings if m['markingId']==PAD).update(deepcopy(PAD_PATCH))
    assert after['floorMarkings']==expected_markings, 'Unrelated marking changed'
    for op in operations(before,catalog):
        if op['op']=='place_asset':
            p=op['placement']
            assert new[p['placementId']]==p
    areas={k:footprint(new[P+k],catalog) for k in KINDS}
    for kind in ['centre']:
        x0,z0,x1,z1=areas[kind]
        assert 55<=x0<x1<=67 and 63.55<=z0<z1<=71.05, 'Equipment outside the exercise pad'
    wx0,wz0,wx1,wz1=areas['wagon']
    assert 75<=wx0<wx1<=81 and 53<=wz0<wz1<=61, 'Wagon outside blue-marked area'
    assert 62-wz1>=1.5, 'Wagon too close to barbecue patio'
    assert len(after['placements'])==len(before['placements'])-1
    assert not any(p['assetId']==A+'weights' for p in after['placements']), 'Misidentified car must not be placed'
    return dict(removedPlacements=sorted(REMOVED),newModels=2,preservedPlacements=len(old)-3,
        footprints=areas,accessoryAssembly='pending correct source; assembly.STEP contains a car',
        existingRouteUnchanged=True,patioAndWallStationsUnchanged=True,siteNotEnlarged=True)


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
    entries=[json.loads((ROOT/'generated/industrial_assets/local_library'/('gym-fitness-centre-'+k)/'catalog-entry.json').read_text()) for k in KINDS]
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
        limitations=['Concept arrangement; exercise operating clearances and equipment load ratings are unverified.',
            'Wagon STL has no units. Centimetres are inferred from its proportions; physical scale needs confirmation.']))
    profile=json.loads((ROOT/'.runtime/private-gym-calisthenics-20261009/profile.json').read_text())
    profile.update(profileId='private-gym-fitness-centre',origin='http://127.0.0.1:8570',dataRoot=str(OUT),
        backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,cameraFov=50,
        requiredAssets=[A+k for k in KINDS],shots=[
            shot('01-fitness-centre',(70,8,59),(61,1.1,67)),
            shot('02-centre-detail',(67,3.5,63),(61,1.5,68)),
            shot('03-wagon',(72,3.8,61),(78.3,1.1,57.1)),
            shot('04-outdoor-overview',(91,29,89),(63,0,61))],
        finalShot=shot('05-saved-outdoor-area',(86,24,87),(63,0,61))))
    print(json.dumps(checks))


if __name__=='__main__':
    main()
