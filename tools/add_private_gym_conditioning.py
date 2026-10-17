"""Add four lane-aligned sleds and four flat gold tire-training hammers."""
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
sys.path[:0] = [str(ROOT), str(ROOT/'tools'),
    str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'),
    str(ROOT/'.runtime/model-import-20261002/mesh-dependencies')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import canonicalize_quaternion, layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.spatial import placement_spatial_records
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT = ROOT/'.runtime/private-gym-conditioning-20261009'
P = 'pl-gym-conditioning-'
A = 'asset-gym-conditioning-'
TIRES = ['pl-private-gym-fields-'+k for k in
    ['training-tire-1','training-tire-2','training-tire-3','wheel-station']]


def operations(before, catalog):
    placements = {p['placementId']:p for p in before['placements']}
    markings = {m['markingId']:m for m in before['floorMarkings']}
    lane_end = markings['fm-private-gym-fields-lane-distance-4']['transform']['position']['x']
    ops = []
    def place(kind, index, x, z, yaw, reference):
        q = math.radians(yaw)/2
        ops.append(dict(op='place_asset',placement=dict(placementId=P+kind+'-'+str(index),assetId=A+kind,
            assetDefinitionRevision=catalog[A+kind]['assetDefinitionRevision'],positionMode='manual',
            transform=dict(position=dict(x=x,y=0,z=z),quaternion=canonicalize_quaternion(dict(x=0,y=math.sin(q),z=0,w=math.cos(q))),scale=1),
            snapRelationship=None,metadata=dict(instanceLabel=('Lane Sled ' if kind=='sled' else 'Gold Training Hammer ')+str(index),
                inputMethod='independent-authoring',authoredReference=reference))))
    for i, pid in enumerate(TIRES, 1):
        tire = placements[pid]['transform']['position']
        place('hammer',i,tire['x'],tire['z']-1.3,90,pid)
        lane_id = 'fm-private-gym-fields-lane-number-'+str(i)
        z = markings[lane_id]['transform']['position']['z']
        # Source handles are at +X; keeping yaw zero points the sled into the -X lane.
        place('sled',i,lane_end+.65,z,0,lane_id)
    return ops


def audit(before, after, catalog):
    old = {p['placementId']:p for p in before['placements']}
    new = {p['placementId']:p for p in after['placements']}
    assert all(new.get(pid)==p for pid,p in old.items()), 'Existing placement changed'
    expected = {P+k+'-'+str(i) for k in ['sled','hammer'] for i in range(1,5)}
    assert new.keys()-old.keys() == expected
    for key,value in before.items():
        if key not in {'placements','updatedAt'}:
            assert after[key] == value, ('Unrelated layout change',key)
    for op in operations(before,catalog):
        p = op['placement']
        assert new[p['placementId']] == p
    lane_centers = []
    for i,pid in enumerate(TIRES,1):
        hammer, sled = new[P+'hammer-'+str(i)],new[P+'sled-'+str(i)]
        h = placement_spatial_records(hammer,catalog[A+'hammer'])[0]
        s = placement_spatial_records(sled,catalog[A+'sled'])[0]
        assert abs(h.minimum_y) < 1e-7 and .08 < h.maximum_y < .09, 'Hammer is not flat on ground'
        assert abs(s.minimum_y) < 1e-7 and 1 < s.maximum_y < 1.02, 'Sled is not upright'
        hx = [p[0] for p in h.polygon]
        hz = [p[1] for p in h.polygon]
        assert abs(max(hx)-min(hx)-1.2) < 1e-5
        assert abs(max(hz)-min(hz)-.2) < 1e-5
        tire = old[pid]['transform']['position']
        assert hammer['transform']['position']['x'] == tire['x']
        assert max(hz) < tire['z']-.6, 'Hammer intersects tire approach'
        assert sled['transform']['quaternion'] == dict(x=0,y=0,z=0,w=1)
        center = sled['transform']['position']['z']
        assert all(abs(z-center)<1 for x,z in s.polygon), 'Sled crosses its lane width'
        lane_centers.append(center)
    assert lane_centers == [44,46,48,50]
    return dict(sleds=4,hammers=4,sledTravelDirection='-X',hammerLongAxis='X',hammerHeightMeters=.083,
        originalPlacementsPreserved=len(old),groundAndMarkingsUnchanged=True,nativeScalePreserved=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish-assets','save'])
    args = parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest, staged = ROOT/PRIVATE_ASSET_MANIFEST, OUT/'staged-project'
    if args.phase != 'stage':
        report = json.loads((OUT/'report.json').read_text())
        assert target.read_bytes()==(OUT/'before.json').read_bytes(), 'Saved gym changed'
        if args.phase == 'publish-assets':
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
    entries=[json.loads((ROOT/'generated/industrial_assets/local_library'/('gym-conditioning-'+k)/'catalog-entry.json').read_text()) for k in ['sled','hammer']]
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
        limitations=['Concept equipment arrangement; exercise swing space, loads and operational safety are not qualified.']))
    profile=json.loads((ROOT/'.runtime/private-gym-patio-20261009/profile.json').read_text())
    profile.update(profileId='private-gym-conditioning',origin='http://127.0.0.1:8568',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,cameraFov=50,
        requiredAssets=[A+'sled',A+'hammer'],shots=[
            shot('01-training-overhead',(75,21,62),(61,0,50)),
            shot('02-four-sleds',(74,2.5,51),(70.2,.4,46.5)),
            shot('03-gold-hammers',(69,3.5,52),(62,.15,55.5)),
            shot('04-hammer-flat',(65.5,1.4,53.6),(64,.1,55.1)),
            shot('05-sled-direction',(73,1.6,44),(69.7,.5,44))],
        finalShot=shot('06-saved-training',(76,12,62),(62,0,50))))
    print(json.dumps(checks))


if __name__=='__main__':
    main()
