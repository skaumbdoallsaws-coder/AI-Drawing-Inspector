"""Add the three original artworks to Private Gym's existing support walls."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write
from tools.add_factory02_parking_office import hashes
from tools.private_gym_reception_art import wall_glb, RELATIVE

OUT=ROOT/'.runtime/private-gym-training-art-20261007'
DOWNLOADS=Path('C:/Users/might/Downloads')
# Left/right are from the gym floor looking toward the support rooms (+X).
ARTWORKS=[
    ('eagle','Staff West','Patriotic Eagle in Flight.png',6,54.2,3.5),
    ('warrior','Support West A','Zulu Warrior with Shield and Spear.png',8,51.2,16.3),
    ('panther','Support West B','Fierce Black Panther Mascot.png',6,51.2,26.8),
]


def audit(before,after,replacements,expected_count=3):
    expected=deepcopy(before)
    assert len(replacements)==expected_count
    for pid,ref in replacements.items():
        next(p for p in expected['placements'] if p['placementId']==pid).update(ref)
    expected['updatedAt']=after['updatedAt']
    assert expected==after,'Only the authorized wall asset references may change'


def main():
    global OUT
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-assets',action='store_true')
    parser.add_argument('--save',action='store_true')
    parser.add_argument('--eagle-full-wall',action='store_true')
    args=parser.parse_args()
    if args.eagle_full_wall:OUT=ROOT/'.runtime/private-gym-eagle-full-wall-20261007'
    artworks=ARTWORKS[:1] if args.eagle_full_wall else ARTWORKS
    target=STORE/RELATIVE;manifest=ROOT/PRIVATE_ASSET_MANIFEST
    staged=OUT/'staged-project'
    if args.save:
        report=json.loads((OUT/'report.json').read_text())
        native=json.loads((OUT/'native-check.json').read_text())
        before=json.loads((OUT/'before.json').read_text())
        candidate=json.loads((OUT/'candidate.json').read_text())
        assert native['status']=='preview-verified'
        assert native['candidateHash']==hashlib.sha256((OUT/'candidate.json').read_bytes()).hexdigest()
        assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed during review'
        assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
        for artifact in report['artifacts']:
            assert (ROOT/artifact).read_bytes()==(staged/artifact).read_bytes()
        audit(before,candidate,report['replacements'],len(artworks))
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        finally:host.close()
        audit(before,saved['layout'],report['replacements'],len(artworks))
        after_hashes=hashes(target.parent)
        assert all(after_hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
        write(OUT/'saved.json',saved['layout'])
        report.update(status='saved',savedRevision=saved['revision'],otherLayoutsUnchanged=True)
        write(OUT/'report.json',report)
        print(json.dumps(dict(status=report['status'],savedRevision=saved['revision'])))
        return
    OUT.mkdir(parents=True,exist_ok=True)
    raw=target.read_bytes();before=json.loads(raw)
    catalog_bytes=manifest.read_bytes();library=json.loads(catalog_bytes)
    for name,payload in [('before.json',raw),('catalog-before.json',catalog_bytes)]:
        snapshot=OUT/name
        if snapshot.exists():assert snapshot.read_bytes()==payload,'Staging source changed: '+name
        else:snapshot.write_bytes(payload)
    bindings=[];artifacts=[]
    for key,label,filename,width,x,z in artworks:
        wall=next(p for p in before['placements'] if p.get('metadata',{}).get('instanceLabel')==label)
        assert wall['transform']['position']==dict(x=x,y=0,z=z)
        assert wall['transform']['quaternion']==dict(x=0,y=.707106781,z=0,w=.707106781)
        old=next(a for a in library['assets'] if a['assetId']==wall['assetId'])
        assert old['dimensions']==dict(width=width,depth=.15,height=3)
        asset_key=key+'-full-wall' if args.eagle_full_wall else key
        aid='asset-private-gym-training-'+asset_key
        assert not any(a['assetId']==aid for a in library['assets'])
        folder=Path('generated/industrial_assets/private_gym/training-art')/asset_key
        original=(DOWNLOADS/filename).read_bytes()
        png=(ROOT/folder/'mural.png').read_bytes() if args.eagle_full_wall else original
        fit='full' if args.eagle_full_wall else 'contain'
        artifact=(folder/'model.glb').as_posix()
        texture=(folder/'artwork.png').as_posix()
        payload=wall_glb(png,old['dimensions'],fit=fit,face=-1,name=key.title()+' wall artwork')
        for relative,data in [(artifact,payload),(texture,png)]:
            dest=staged/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(data)
            artifacts.append(relative)
        source=dict(kind='generated-wide-adaptation' if args.eagle_full_wall else 'original-user-artwork',
                    originalFile=filename,sha256=hashlib.sha256(png).hexdigest(),
                    originalSha256=hashlib.sha256(original).hexdigest(),
                    fit=fit,face='local-negative-z',imageModified=args.eagle_full_wall)
        library['assets'].append(dict(assetId=aid,displayName='Private Gym '+key.title()+' Wall',
            category='Building Structures',dimensions=old['dimensions'],sourceToCanonical=IDENTITY,
            artifact=artifact,tags=['wall','gym','artwork'],source=source,
            description='Existing partition with '+('full-wall panoramic artwork' if args.eagle_full_wall else 'centered, original artwork')+' facing the gym floor.'))
        bindings.append(dict(placementId=wall['placementId'],assetId=aid,wallLabel=label,artwork=key,source=source))
    library['summary']['total']=len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        replacements={b['placementId']:{k:catalog[b['assetId']][k] for k in ('assetId','assetDefinitionRevision')} for b in bindings}
        candidate=deepcopy(before)
        for p in candidate['placements']:
            if p['placementId'] in replacements:p.update(replacements[p['placementId']])
        audit(before,candidate,replacements,len(artworks))
        saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
        candidate=saved['layout'];audit(before,candidate,replacements,len(artworks))
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    report=dict(status='validated',baseRevision=layout_revision(before),replacements=replacements,
        artifacts=artifacts,bindings=bindings,unchangedPlacements=len(before['placements'])-len(artworks),
        layoutHashes=hashes(target.parent),unchangedGeometry=True)
    if args.publish_assets:
        assert manifest.read_bytes()==catalog_bytes and target.read_bytes()==raw
        for artifact in artifacts:assert not (ROOT/artifact).exists()
        for artifact in artifacts:RevisionedAuthorityRepository._atomic_write(ROOT/artifact,(staged/artifact).read_bytes())
        RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
        report['status']='assets-published'
    write(OUT/'report.json',report)
    profile=json.loads((ROOT/'.runtime/private-gym-reception-art-20261007/profile.json').read_text())
    profile.update(profileId='private-gym-eagle-full-wall-review' if args.eagle_full_wall else 'private-gym-training-art-review',
        origin='http://127.0.0.1:8540' if args.eagle_full_wall else 'http://127.0.0.1:8539',dataRoot=str(OUT),
        backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],
        requiredAssets=[b['assetId'] for b in bindings],
        shots=[dict(name=key,position=dict(x=x-7,y=1.9,z=z),target=dict(x=x,y=1.5,z=z),
                    thresholds=dict(red=500,yellow=500,blue=500) if key=='eagle' else dict(dark=1000,detail=1000))
               for key,label,filename,width,x,z in artworks]+[
                   dict(name='all-three',position=dict(x=33,y=8,z=16),target=dict(x=52,y=1.5,z=16),thresholds=dict(detail=1000))],
        finalShot=dict(name='saved-full-wall-eagle',position=dict(x=47.2,y=1.9,z=3.5),target=dict(x=54.2,y=1.5,z=3.5),thresholds=dict(red=500,yellow=500,blue=500)) if args.eagle_full_wall else
            dict(name='saved-three-walls',position=dict(x=33,y=8,z=16),target=dict(x=52,y=1.5,z=16),thresholds=dict(detail=1000))))
    print(json.dumps(dict(status=report['status'],unchangedPlacements=report['unchangedPlacements'],bindings=bindings)))


if __name__=='__main__':main()
