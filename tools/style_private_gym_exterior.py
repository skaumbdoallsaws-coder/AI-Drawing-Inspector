"""Stage and save exterior-only charcoal, stone and supplied gold artwork."""
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
from PIL import Image
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes

OUT=ROOT/'.runtime/private-gym-exterior-20261007'
SOURCE=Path('C:/Users/might/Videos/gym wall arts/Gym emblem')
COLOR='#55585a'


def audit(before,after):
    expected=deepcopy(before)
    expected['extensions']['facilityPerimeterWalls']=after['extensions']['facilityPerimeterWalls']
    expected['updatedAt']=after['updatedAt']
    assert expected==after,'Unrelated layout content changed'
    old=deepcopy(before['extensions']['facilityPerimeterWalls'])
    new=deepcopy(after['extensions']['facilityPerimeterWalls'])
    old['settings'].pop('exteriorFinish',None)
    new['settings'].pop('exteriorFinish',None)
    assert old==new,'Physical walls or openings changed'
    return dict(unchangedPlacements=len(before['placements']),physicalGeometryUnchanged=True,
                interiorMuralsUnchanged=True,artworkCount=3,imagesModified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish-art','save'])
    args=parser.parse_args()
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    if args.phase!='stage':
        report=json.loads((OUT/'report.json').read_text())
        if args.phase=='save' and report['status']=='saved':
            assert json.loads(target.read_bytes())==json.loads((OUT/'saved.json').read_text())
            print(json.dumps(dict(status='already-saved')));return
        assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed during review'
        for item in report['artifacts']:
            raw=(OUT/'staged-project'/item['path']).read_bytes()
            assert hashlib.sha256(raw).hexdigest()==item['sha256']
            dest=ROOT/item['path']
            if args.phase=='publish-art' and not dest.exists():
                dest.parent.mkdir(parents=True,exist_ok=True)
                RevisionedAuthorityRepository._atomic_write(dest,raw)
            assert dest.read_bytes()==raw
        if args.phase=='publish-art':
            report['status']='art-published'
        else:
            native=json.loads((OUT/'native-check.json').read_text())
            raw=(OUT/'candidate.json').read_bytes()
            assert native['status']=='preview-verified'
            assert native['candidateHash']==hashlib.sha256(raw).hexdigest()
            art=native['diagnostics']['exteriorArtwork']
            assert len(art)==3 and all(a['status']=='ready' for a in art)
            candidate=json.loads(raw);before=json.loads((OUT/'before.json').read_text())
            audit(before,candidate)
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            finally:host.close()
            audit(before,receipt['layout'])
            write(OUT/'saved.json',receipt['layout'])
            report.update(status='saved',savedRevision=receipt['revision'])
            after=saved_hashes()
            assert all(after[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged']=True
        write(OUT/'report.json',report)
        print(json.dumps(dict(status=report['status'])));return

    OUT.mkdir(parents=True,exist_ok=True)
    raw=target.read_bytes();before=json.loads(raw)
    snapshot=OUT/'before.json'
    if snapshot.exists():assert snapshot.read_bytes()==raw,'Saved base changed'
    else:snapshot.write_bytes(raw)
    settings=deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    finish=dict(color=COLOR,jointColor='#303437',panelWidthMeters=2,panelHeightMeters=1.2,
                jointWidthMeters=.014,artworks=[],accentStrips=[],wallFaces=[])
    artifacts=[]
    specs=[('apex-emblem','Apex Gym Wolf Emblem.png',0,8,12,0,3.6,'#e3e0d8'),
           ('discipline','ChatGPT Image Oct 7, 2026, 08_37_57 PM-1.png',3,19,8,.2,3.2,None),
           ('higher-everyday','ChatGPT Image Oct 7, 2026, 08_37_58 PM-2.png',0,42,12,.2,3.2,None)]
    for key,name,edge,start,width,bottom,height,backing in specs:
        original=SOURCE/name;payload=original.read_bytes();digest=hashlib.sha256(payload).hexdigest()
        path='generated/facility-wall-art/'+digest+'.png'
        staged=OUT/'staged-project'/path;staged.parent.mkdir(parents=True,exist_ok=True);staged.write_bytes(payload)
        # Frame the artwork, ignoring near-transparent export noise; keep PNG bytes intact.
        with Image.open(original) as image:
            assert image.format=='PNG'
            w,h=image.size
            bounds=image.getchannel('A').point(lambda a:255 if a>=16 else 0).getbbox() if 'A' in image.getbands() else (0,0,w,h)
            assert bounds
            x0,y0,x1,y1=bounds
            margin=round(min(w,h)*.025)
            x0,y0,x1,y1=max(0,x0-margin),max(0,y0-margin),min(w,x1+margin),min(h,y1+margin)
            uv=[x0/w,1-y1/h,x1/w,1-y0/h]
        art=dict(artworkId=key,edge=edge,startMeters=start,widthMeters=width,bottomMeters=bottom,
                 heightMeters=height,imagePath='/'+path,uv=uv)
        if backing:art.update(backingColor=backing,borderColor='#d0a144')
        finish['artworks'].append(art)
        artifacts.append(dict(path=path,sha256=digest,source=str(original),imageModified=False,
                              visiblePixelBounds=bounds,displayPixelBounds=[x0,y0,x1,y1],framingAlphaThreshold=16))
    for edge,start in [(0,.3),(0,4.8),(0,7.15),(0,20.2),(0,40),(0,55.8),(3,.35),(3,18.5),(3,27.5),(2,.3),(2,28.7),(2,31.2)]:
        finish['accentStrips'].append(dict(edge=edge,startMeters=start,widthMeters=.045,color='#c9a044'))
    faces={'court-back':'positive_z','court-left':'negative_z','court-right':'positive_z',
           'boxing-south':'negative_z','boxing-east':'positive_z','boxing-north':'positive_z','boxing-north-return':'positive_z'}
    for key,face in faces.items():
        placement=next(p for p in before['placements'] if p['placementId']=='pl-private-gym-sports-'+key)
        finish['wallFaces'].append(dict(placementId=placement['placementId'],assetDefinitionRevision=placement['assetDefinitionRevision'],face=face,color=COLOR))
    settings['exteriorFinish']=finish
    ops=[dict(op='set_perimeter_walls',wallSettings=settings)]
    candidate=apply_facility_layout_operations(before,ops)['document']
    checks=audit(before,candidate)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=ROOT)
    try:
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally:host.close()
    write(OUT/'candidate.json',receipt['layout']);write(OUT/'operations.json',ops)
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),checks=checks,artifacts=artifacts,layoutHashes=saved_hashes()))
    profile=json.loads((ROOT/'.runtime/private-gym-three-bags-20261007/profile.json').read_text())
    profile.update(profileId='private-gym-exterior',origin='http://127.0.0.1:8544',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,position,target):return dict(name=name,position=dict(zip(('x','y','z'),position)),target=dict(zip(('x','y','z'),target)),thresholds=dict(detail=1000,yellow=500))
    shots=[shot('01-exterior-overview',(-24,26,-36),(27,0,12)),
           shot('02-front-elevation',(30,7,-40),(30,1.8,0)),
           shot('03-apex-emblem',(14,2.5,-11),(14,1.8,0)),
           shot('04-discipline',(-11,2.5,7),(0,1.8,7)),
           shot('05-higher-everyday',(48,2.5,-12),(48,1.8,0))]
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],requiredAssets=[],requiredWallArt=[a['artworkId'] for a in finish['artworks']],
        shots=shots,finalShot=shot('06-saved-exterior',(-24,24,-32),(24,0,10))))
    print(json.dumps(dict(status='validated',checks=checks)))


if __name__=='__main__':main()
