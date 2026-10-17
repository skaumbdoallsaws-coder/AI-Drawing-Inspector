"""Stage and revision-bound save of Private Gym's interior graphite paint."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
if sys.version_info[:2]==(3,14):
    sys.path.insert(0,str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'))
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT=ROOT/'.runtime/private-gym-interior-paint-20261008'
PREVIOUS=ROOT/'.runtime/private-gym-interior-gallery-20261008'
COLOR='#3b4147'
WALL_IDS={
    'pl-2f8c760de4adbb1a83cc1629', 'pl-9b54f9f414ff77a8cad8cb2d',
    'pl-9169ff069ba0815c351d6a03', 'pl-4b054c269e90a31768b0cfff',
    'pl-c57cb8a4a0b92614d2731649', 'pl-8e028757b1982d3d17b9d714',
}


def audit(before,after):
    expected=deepcopy(before)
    expected['updatedAt']=after['updatedAt']
    expected['extensions']['facilityPerimeterWalls']['settings']['interiorColor']=COLOR
    found=set()
    for p in expected['placements']:
        if p['placementId'] in WALL_IDS:
            assert p['metadata']['gymRole']=='architecture'
            assert 0<=p['transform']['position']['x']<=60 and 0<=p['transform']['position']['z']<=30
            p['appearance']={'color':COLOR};found.add(p['placementId'])
    assert found==WALL_IDS
    assert expected==after,'Unrequested layout content changed'
    return dict(interiorColor=COLOR,partitionWalls=6,exteriorAndArtworkUnchanged=True,
                equipmentAndGeometryUnchanged=True,adjoiningSportsAreasUnchanged=True)


def main(phase):
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    if phase=='save':
        report=json.loads((OUT/'report.json').read_text())
        if report['status']=='saved':
            assert json.loads(target.read_bytes())==json.loads((OUT/'saved.json').read_bytes())
            print('Already saved');return
        assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed during review'
        raw=(OUT/'candidate.json').read_bytes();native=json.loads((OUT/'native-check.json').read_text())
        assert native['status']=='preview-verified' and native['candidateHash']==hashlib.sha256(raw).hexdigest()
        before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads(raw);audit(before,candidate)
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        finally:host.close()
        audit(before,receipt['layout']);write(OUT/'saved.json',receipt['layout'])
        after=saved_hashes()
        assert all(after[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
        report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
        write(OUT/'report.json',report);print(json.dumps(dict(status='saved')));return
    OUT.mkdir(parents=True,exist_ok=True)
    raw=target.read_bytes();before=json.loads(raw);snapshot=OUT/'before.json'
    if snapshot.exists():assert snapshot.read_bytes()==raw,'Saved base changed'
    else:snapshot.write_bytes(raw)
    settings=deepcopy(before['extensions']['facilityPerimeterWalls']['settings']);settings['interiorColor']=COLOR
    ops=[dict(op='set_perimeter_walls',wallSettings=settings),
         dict(op='set_appearance',placementIds=sorted(WALL_IDS),color=COLOR)]
    candidate=apply_facility_layout_operations(before,ops)['document'];checks=audit(before,candidate)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=ROOT)
    try:
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally:host.close()
    audit(before,receipt['layout']);write(OUT/'candidate.json',receipt['layout']);write(OUT/'operations.json',ops)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,layoutHashes=saved_hashes()))
    profile=json.loads((PREVIOUS/'profile.json').read_text())
    profile.update(profileId='private-gym-interior-paint',origin='http://127.0.0.1:8551',dataRoot=str(OUT),
                   backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    config=json.loads((PREVIOUS/'review-config.json').read_text());config['profileId']=profile['profileId']
    config['shots']=config['shots'][:6]
    def shot(name,p,t):
        return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    config['shots'] += [shot('07-partitions',(44,4,21),(51.2,1.5,21)),
                        shot('08-exterior',(30,7,-14),(30,1.8,0))]
    config['finalShot']=shot('09-saved-graphite',(18,5,19),(0,1.95,17))
    write(OUT/'review-config.json',config)
    print(json.dumps(dict(status='validated',checks=checks)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','save'])
    main(parser.parse_args().phase)
