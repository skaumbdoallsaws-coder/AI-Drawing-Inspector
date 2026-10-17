"""Place the corrected SHOWROOM_ASSEMBLY beside the outdoor wall stations."""
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
from tools.add_private_gym_fitness_centre import footprint
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT=ROOT/'.runtime/private-gym-showroom-20261009'
ASSET='asset-gym-fitness-centre-showroom'
PLACEMENT='pl-gym-showroom-accessories'
PAD='fm-private-gym-fields-rack-pad'


def operations(before,catalog):
    pad=next(m for m in before['floorMarkings'] if m['markingId']==PAD)
    assert pad['transform']==dict(position=dict(x=47.4,y=.003,z=67),rotationDegrees=270)
    assert pad['width']==9 and pad['depth']==6, 'Reviewed wall-station pad changed'
    assert not any(p['placementId']==PLACEMENT for p in before['placements']), 'Assembly already installed'
    return [dict(op='place_asset',placement=dict(placementId=PLACEMENT,assetId=ASSET,
        assetDefinitionRevision=catalog[ASSET]['assetDefinitionRevision'],positionMode='manual',
        transform=dict(position=dict(x=49.1,y=0,z=70),quaternion=dict(x=0,y=0,z=0,w=1),scale=1),
        snapRelationship=None,metadata=dict(instanceLabel='Dumbbells, Plates and Kettlebells',
            inputMethod='independent-authoring')))]


def audit(before,after,catalog):
    old={p['placementId']:p for p in before['placements']}
    new={p['placementId']:p for p in after['placements']}
    assert new.keys()-old.keys()=={PLACEMENT} and not old.keys()-new.keys()
    assert all(new[pid]==p for pid,p in old.items()), 'Existing equipment changed'
    assert new[PLACEMENT]==operations(before,catalog)[0]['placement']
    for key,value in before.items():
        if key not in {'placements','updatedAt'}:
            assert after[key]==value, ('Unrelated layout change',key)
    x0,z0,x1,z1=footprint(new[PLACEMENT],catalog)
    assert 44.4<=x0<x1<=50.4 and 62.5<=z0<z1<=71.5, 'Weights leave the reviewed wall-station pad'
    approaches=[]
    for i in range(1,4):
        bounds=footprint(new['pl-gym-calisthenics-pushup-supports-'+str(i)],catalog)
        approaches.append(x0-bounds[2])
    assert min(approaches)>=2, 'Weights crowd push-up support approach'
    assert z0>68.5, 'Central station approach must remain open'
    assert not any(p['assetId']=='asset-gym-fitness-centre-weights' for p in after['placements'])
    return dict(source='SHOWROOM_ASSEMBLY.stp',placement=PLACEMENT,footprint=[x0,z0,x1,z1],
        preservedPlacements=len(old),minimumSupportGapMeters=min(approaches),
        originalGroundAndMarkingsUnchanged=True,sourceColoursAndNativeScalePreserved=True,
        chosenLocation='Outer end of wall-mount pad; does not obstruct the fitness-centre approach',
        alternative='Fitness-centre front would need a pad extension to retain a separate approach strip')


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
    entry=json.loads((ROOT/'generated/industrial_assets/local_library/gym-fitness-centre-showroom/catalog-entry.json').read_text())
    assert entry['assetId']==ASSET and entry['source']['fileName']=='SHOWROOM_ASSEMBLY.stp'
    assert not any(e['assetId']==ASSET for e in library['assets'])
    library['assets'].append(entry)
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
        assetHashes={entry['artifact']:hashlib.sha256((ROOT/entry['artifact']).read_bytes()).hexdigest()},
        limitations=['Source assembly arrangement retained; exercise operating clearances and storage safety require independent review.']))
    profile=json.loads((ROOT/'.runtime/private-gym-fitness-centre-20261009/profile.json').read_text())
    profile.update(profileId='private-gym-showroom',origin='http://127.0.0.1:8571',dataRoot=str(OUT),
        backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,cameraFov=50,
        requiredAssets=[ASSET],shots=[
            shot('01-accessory-details',(52,2.8,73),(49.1,.15,70)),
            shot('02-wall-station-context',(57,7,77),(47,1,67)),
            shot('03-whole-outdoor-area',(84,24,87),(61,0,61))],
        finalShot=shot('04-saved-wall-stations',(57,6,77),(47.3,.8,68))))
    print(json.dumps(checks))


if __name__=='__main__':
    main()
