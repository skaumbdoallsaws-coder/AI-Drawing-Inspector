"""Revision-bound interior wall graphics; original PNGs and layout stay intact."""
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
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT=ROOT/'.runtime/private-gym-interior-gallery-20261008'
SOURCE=Path('C:/Users/might/Videos/gym wall arts')
PREFIX='apex-interior-'
HEIGHT=3.0
MARGIN=.2
BOTTOM=.35
# Coordinates follow the red-marked perimeter runs, not existing feature walls.
ARRANGEMENT=[
    ('h04','Runner',0,16),('a08','Horse',0,24),('h03','Tennis',0,32),
    ('h02','Martial Arts',0,41),('h06','Javelin',0,49),
    ('a01','Lion',3,7),('h01','Warrior',3,14),('a06','Bear',3,20),('a09','Elephant',3,26),
    ('a02','Tiger',2,6),('a03','Wolf Portrait',2,15),('a05','Wolf',2,24),
    ('a07','Cobra',2,37),('h07','Hammer Throw',2,44),('h08','Soccer',2,54),
    ('a04','Eagle',1,15.5),('h05','Basketball',1,19.5),('h09','Combat Athlete',1,26.2),
]


def inventory():
    from PIL import Image
    records=[]
    for folder in ('animals','human'):
        paths=sorted((SOURCE/folder).glob('*.png'));assert len(paths)==9
        for index,path in enumerate(paths,1):
            with Image.open(path) as image:
                assert image.format=='PNG'
                records.append(dict(key=('a' if folder=='animals' else 'h')+f'{index:02}',folder=folder,
                    source=str(path),width=image.width,height=image.height,sha256=hashlib.sha256(path.read_bytes()).hexdigest()))
    assert len({r['sha256'] for r in records})==18
    write(OUT/'inventory.json',records);return records


def artwork_record(record,edge,coordinate):
    width=HEIGHT*record['width']/record['height']+MARGIN
    along=coordinate if edge in (0,1) else (60 if edge==2 else 30)-coordinate
    return dict(artworkId=PREFIX+record['key'],edge=edge,side='interior',startMeters=along-width/2,
        widthMeters=width,bottomMeters=BOTTOM,heightMeters=HEIGHT+MARGIN,
        imagePath='/generated/facility-wall-art/'+record['sha256']+'.png',uv=[0,0,1,1])


def audit(before,after,records):
    expected=deepcopy(before)
    old=before['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks']
    artworks=after['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks']
    assert artworks[:len(old)]==old,'Existing wall artwork changed'
    expected['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks']=artworks
    expected['updatedAt']=after['updatedAt']
    assert expected==after,'Content beyond the new wall graphics changed'
    added=artworks[len(old):];assert len(added)==len(records)==18
    by_key={r['key']:r for r in records}
    assert added==[artwork_record(by_key[key],edge,c) for key,_,edge,c in ARRANGEMENT]
    for art in added:
        assert art['side']=='interior' and 'backingColor' not in art and 'borderColor' not in art
        settings=before['extensions']['facilityPerimeterWalls']['settings']
        assert art['bottomMeters']+art['heightMeters']<=settings['heightMeters']
        for door in settings['openings']:
            if door['edge']==art['edge']:
                assert art['startMeters']+art['widthMeters']+.3<=door['startMeters'] or art['startMeters']-.3>=door['endMeters']
        if art['edge']==0:assert art['startMeters']>10.1,'Reception mural obstructed'
    return dict(artworksAdded=18,originalPlacementsUnchanged=len(before['placements']),
        originalWallsAndMuralsUnchanged=True,sourceImagesUnmodified=True,doorwaysClear=True,
        displayedImageHeightMeters=HEIGHT,displayedImageWidthMeters=2.25,walls=dict(front=5,left=4,rear=6,right=3))


def main(phase):
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');staged=OUT/'staged-project'
    if phase in ('publish-art','save'):
        report=json.loads((OUT/'report.json').read_text())
        if phase=='save' and report['status']=='saved':
            assert json.loads(target.read_bytes())==json.loads((OUT/'saved.json').read_bytes());print('Already saved');return
        assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed during review'
        for item in report['artifacts']:
            raw=(staged/item['path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==item['sha256']
            dest=ROOT/item['path']
            if phase=='publish-art' and not dest.exists():RevisionedAuthorityRepository._atomic_write(dest,raw)
            assert dest.read_bytes()==raw
        if phase=='publish-art':report['status']='art-published'
        else:
            raw=(OUT/'candidate.json').read_bytes();native=json.loads((OUT/'native-check.json').read_text())
            assert native['status']=='preview-verified' and native['candidateHash']==hashlib.sha256(raw).hexdigest()
            ready={a['artworkId'] for a in native['diagnostics']['exteriorArtwork'] if a['status']=='ready'}
            assert {PREFIX+r['key'] for r in report['records']}<=ready
            before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads(raw);audit(before,candidate,report['records'])
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            finally:host.close()
            audit(before,receipt['layout'],report['records']);write(OUT/'saved.json',receipt['layout'])
            after=saved_hashes();assert all(after[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
        write(OUT/'report.json',report);print(json.dumps(dict(status=report['status'])));return
    OUT.mkdir(parents=True,exist_ok=True);records=inventory()
    if phase=='inventory':print(json.dumps(dict(artworks=len(records))));return
    raw=target.read_bytes();before=json.loads(raw);snapshot=OUT/'before.json'
    if snapshot.exists():assert snapshot.read_bytes()==raw,'Saved base changed'
    else:snapshot.write_bytes(raw)
    artifacts=[];by_key={r['key']:r for r in records}
    assert {r['key'] for r in records}=={a[0] for a in ARRANGEMENT}
    settings=deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    for key,label,edge,c in ARRANGEMENT:
        r=by_key[key];r.update(label=label,edge=edge,coordinate=c)
        png=Path(r['source']).read_bytes();assert hashlib.sha256(png).hexdigest()==r['sha256']
        relative='generated/facility-wall-art/'+r['sha256']+'.png'
        dest=staged/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(png)
        artifacts.append(dict(path=relative,sha256=r['sha256'],source=r['source'],imageModified=False))
        settings['exteriorFinish']['artworks'].append(artwork_record(r,edge,c))
    ops=[dict(op='set_perimeter_walls',wallSettings=settings)]
    candidate=apply_facility_layout_operations(before,ops)['document'];checks=audit(before,candidate,records)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=ROOT)
    try:
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally:host.close()
    audit(before,receipt['layout'],records);write(OUT/'candidate.json',receipt['layout']);write(OUT/'operations.json',ops)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),records=records,checks=checks,
        artifacts=artifacts,layoutHashes=saved_hashes()))
    profile=json.loads((ROOT/'.runtime/private-gym-fields-20261008/profile.json').read_text())
    profile.update(profileId='private-gym-interior-gallery',origin='http://127.0.0.1:8550',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    shots=[shot('01-cardio-gallery',(31,5,16),(31,1.95,0)),shot('02-left-gallery',(12,4,18),(0,1.95,18)),
           shot('03-rear-strength-gallery',(14,5,16),(15,1.95,30)),shot('04-rear-athletic-gallery',(42,5,18),(42,1.95,30)),
           shot('05-right-north-gallery',(56,2.5,16.8),(60,1.9,17.5)),shot('06-right-south-gallery',(56,2.5,26),(60,1.9,26.2))]
    for key,label,edge,c in ARRANGEMENT:
        x,z={0:(c,0),1:(60,c),2:(c,30),3:(0,c)}[edge];nx,nz={0:(0,1),1:(-1,0),2:(0,-1),3:(1,0)}[edge]
        shots.append(shot('art-'+key,(x+nx*4.8,2.05,z+nz*4.8),(x,1.95,z)))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],requiredAssets=[],
        requiredWallArt=[a['artworkId'] for a in settings['exteriorFinish']['artworks']],shots=shots,
        finalShot=shot('07-saved-interior-gallery',(18,5,19),(0,1.95,17))))
    print(json.dumps(dict(status='validated',checks=checks)))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['inventory','stage','publish-art','save'])
    main(parser.parse_args().phase)
