"""Stage, verify and publish scoped APEX equipment material variants."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from tools.apex_equipment_materials import build_variant, source_path, unpack
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

OUT=ROOT/'.runtime/private-gym-equipment-theme-20261008'
PILOT=['asset-gym-commercial-native-multi-gym','asset-gym-commercial-workout-bench']
SPORTS=['asset-gym-sports-boxing-ring','asset-gym-sports-boxing-bag',
        'asset-gym-sports-basketball-hoop','asset-private-gym-fields-soccer-goal','asset-gym-field-goal']
OVERRIDES={
 'asset-gym-sports-boxing-bag':{
   **{str(i):'steel' for i in list(range(44))+[48,49,50,62]},
   **{str(i):'gold_padding' for i in range(44,48)},
 },
 'asset-gym-sports-boxing-ring':{'regions':[
   {'bounds':[[-3.9,.9999,-3.9],[3.9,1.0001,3.9]],'role':'upholstery'},
   {'bounds':[[-3.081,1.21,-3.081],[3.081,2.01,3.081]],'role':'gold_padding'},
   *[{'bounds':[[x,1.01,z],[x+.34,2.4,z+.34]],'role':'upholstery'}
     for x in [-3.22,2.88] for z in [-3.22,2.88]],
 ]},
 'asset-gym-sports-basketball-hoop':{
   '0:0':'gold','0:1':'frame','0:2':'marking','0:3':'gold',
   '0:4':'frame','0:5':'rubber','0:6':'rim_orange','0:7':'steel',
 },
 'asset-private-gym-fields-soccer-goal':{'0':'gold','1':'marking'},
 'asset-gym-field-goal':{'0':'gold'},
 'asset-gym-commercial-native-multi-gym':{
   **{str(i):'steel' for i in [8,32,43,55,69]},
   **{str(i):'upholstery' for i in [65,66]},
   **{str(i):'gold' for i in [57,68]},
 },
 'asset-gym-commercial-workout-bench':{'76':'gold','83':'gold','58':'steel'},
 'asset-gym-expansion-flat-bench':{'3':'steel'},
 'asset-gym-expansion-leg-extension':{'14':'upholstery','15':'steel','0':'rubber'},
}


def audit(before,after,replacements):
    expected=deepcopy(before)
    for p in expected['placements']:
        if p['placementId'] in replacements:p.update(replacements[p['placementId']])
    expected['updatedAt']=after['updatedAt']
    assert expected==after,'Only equipment asset references may change'


def main(phase,pilot=False,outdoor=False,sports=False):
    section='sports' if sports else ('outdoor' if outdoor else ('pilot' if pilot else 'complete'))
    out=OUT/section
    out.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    staged=out/'staged-project'
    if phase=='save':
        report=json.loads((out/'report.json').read_text())
        native=json.loads((out/'native-check.json').read_text())
        raw=(out/'candidate.json').read_bytes()
        assert native['status']=='preview-verified' and native['candidateHash']==hashlib.sha256(raw).hexdigest()
        assert target.read_bytes()==(out/'before.json').read_bytes()
        assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
        for relative in report['artifacts']:
            assert (ROOT/relative).read_bytes()==(staged/relative).read_bytes()
        before=json.loads((out/'before.json').read_bytes());candidate=json.loads(raw)
        audit(before,candidate,report['replacements'])
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        finally:host.close()
        audit(before,receipt['layout'],report['replacements'])
        after=saved_hashes()
        assert all(after[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
        write(out/'saved.json',receipt['layout'])
        report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
        write(out/'report.json',report);print('Saved');return
    before_raw=target.read_bytes();before=json.loads(before_raw)
    catalog_raw=manifest.read_bytes();library=json.loads(catalog_raw)
    for filename,raw in [('before.json',before_raw),('catalog-before.json',catalog_raw)]:
        p=out/filename
        if p.exists():assert p.read_bytes()==raw,'Source changed during staging'
        else:p.write_bytes(raw)
    ids=sorted({p['assetId'] for p in before['placements'] if p['assetId'].startswith('asset-gym-')
                and not any(k in p['assetId'] for k in ['sports','field','inter-v4','pool-table'])})
    if pilot:ids=PILOT
    if outdoor:ids=['asset-gym-field-bike','asset-gym-field-wall-rack']
    if sports:ids=SPORTS
    bindings={};artifacts=[];checks=[]
    extra_file=ROOT/'tools/private_gym_equipment_roles.json'
    extra=json.loads(extra_file.read_text()) if extra_file.exists() else {}
    for aid in ids:
        old=next(a for a in library['assets'] if a['assetId']==aid)
        key=aid.removeprefix('asset-')
        relative=f'generated/industrial_assets/private_gym/apex-equipment/{key}/model.glb'
        overrides={**OVERRIDES.get(aid,{}),**extra.get(aid,{})}
        if aid=='asset-gym-field-wall-rack':
            doc,_=unpack(source_path(old).read_bytes())
            for i,m in enumerate(doc['meshes']):
                if m.get('name','').startswith(('ISO 7089','ISO 4014','ISO 4017','ISO 7041','ISO 4032','Washer')):
                    overrides[str(i)]='steel'
        config_hash=hashlib.sha256((ROOT/'tools/apex_equipment_materials.py').read_bytes()+
                       json.dumps(overrides,sort_keys=True).encode()).hexdigest()
        evidence_file=out/'components'/(key+'.json')
        cached=json.loads(evidence_file.read_text()) if evidence_file.exists() else {}
        if cached.get('authoringConfigHash')==config_hash and (staged/relative).exists():
            payload=(staged/relative).read_bytes();evidence=cached
            assert hashlib.sha256(payload).hexdigest()==cached['displaySha256']
            assert hashlib.sha256((ROOT/cached['source']).read_bytes()).hexdigest()==cached['sourceSha256']
            assert hashlib.sha256((ROOT/old['artifact']).read_bytes()).hexdigest()==cached['previousDisplaySha256']
        else:
            payload,evidence=build_variant(old,overrides)
            evidence['authoringConfigHash']=config_hash
        dest=staged/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload)
        new=deepcopy(old);new.update(assetId=aid+'-apex',displayName=old['displayName']+' - APEX',artifact=relative)
        new['description']=old.get('description','')+' APEX component finishes; original CAD retained unchanged.'
        new['visualImport']={k:v for k,v in evidence.items() if k!='components'}
        if 'measuredGeometry' in new:
            new['measuredGeometry'].update(sourceSha256=evidence['displaySha256'],triangles=evidence['triangleCount'])
        new['tags']=old.get('tags',[])+['APEX','component materials']
        assert not any(a['assetId']==new['assetId'] for a in library['assets'])
        library['assets'].append(new);bindings[aid]=new['assetId'];artifacts.append(relative)
        write(out/'components'/(key+'.json'),evidence)
        checks.append({k:v for k,v in evidence.items() if k!='components'})
        print(json.dumps(checks[-1]),flush=True)
    library['summary']['total']=len(library['assets']);write(staged/PRIVATE_ASSET_MANIFEST,library)
    stage=out/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        candidate=deepcopy(before);replacements={}
        for p in candidate['placements']:
            if p['assetId'] in bindings:
                a=catalog[bindings[p['assetId']]]
                ref={k:a[k] for k in ('assetId','assetDefinitionRevision')}
                p.update(ref);replacements[p['placementId']]=ref
        audit(before,candidate,replacements)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
        candidate=receipt['layout'];audit(before,candidate,replacements)
    finally:host.close()
    write(out/'candidate.json',candidate)
    report=dict(status='validated',baseRevision=layout_revision(before),replacements=replacements,
                artifacts=artifacts,checks=checks,layoutHashes=saved_hashes())
    if phase=='publish':
        assert manifest.read_bytes()==catalog_raw and target.read_bytes()==before_raw
        for relative in artifacts:assert not (ROOT/relative).exists()
        for relative in artifacts:RevisionedAuthorityRepository._atomic_write(ROOT/relative,(staged/relative).read_bytes())
        RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
        report['status']='assets-published'
    write(out/'report.json',report)
    profile=json.loads((ROOT/'.runtime/private-gym-interior-paint-20261008/profile.json').read_text())
    profile.update(profileId='private-gym-equipment-'+section,
                   origin='http://127.0.0.1:'+('8556' if sports else ('8555' if outdoor else ('8552' if pilot else '8553'))),dataRoot=str(out),
                   backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(out/'profile.json',profile)
    shots=[]
    for aid in ids:
        p=next(p for p in before['placements'] if p['assetId']==aid)
        x,y,z=[p['transform']['position'][k] for k in ('x','y','z')]
        shots.append(dict(name=aid.removeprefix('asset-'),position=dict(x=x+3.2,y=y+2.7,z=z+(-3.6 if outdoor else 3.6)),
                          target=dict(x=x,y=y+.8,z=z),thresholds=dict(detail=1000,dark=200)))
    final=dict(name='saved-apex-equipment',position=dict(x=25,y=5,z=20),
               target=dict(x=34,y=1,z=9),thresholds=dict(detail=1000,dark=1000))
    if sports:
        views=[('boxing-ring',(77,5,14),(69.2,1,8)),
               ('boxing-bags',(76,2.5,5),(80,1.5,5)),
               ('basketball-hoop',(71.5,4,27),(71.5,3.3,32.5)),
               ('soccer-west',(10,2.8,50),(4.39,1,48)),
               ('soccer-east',(32,2.8,46),(37.61,1,48)),
               ('training-goal',(48.5,2,65),(48.5,.6,69))]
        shots=[dict(name=n,position=dict(zip('xyz',p)),target=dict(zip('xyz',t)),
                    thresholds=dict(detail=1000)) for n,p,t in views]
        final={**shots[0],'name':'saved-apex-boxing'}
    write(out/'review-config.json',dict(profileId=profile['profileId'],requiredAssets=list(bindings.values()),
          minimumAssetMeshes=1,shots=shots,finalShot=final))
    print(json.dumps(dict(status=report['status'],assets=len(ids),placements=len(replacements))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish','save'])
    scope=parser.add_mutually_exclusive_group()
    scope.add_argument('--pilot',action='store_true')
    scope.add_argument('--outdoor',action='store_true')
    scope.add_argument('--sports',action='store_true')
    args=parser.parse_args();main(args.phase,args.pilot,args.outdoor,args.sports)
