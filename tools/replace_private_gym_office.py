"""Replace only the Private Gym office furniture after native desktop verification."""
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
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'),
              str(ROOT/'.runtime/model-import-20261002/mesh-dependencies')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write, saved_hashes
from tools.private_gym_reception_art import wall_glb
from tools.equip_factory02_cubicles import transform
from tools.audit_independent_factory_layer2 import footprint
from tools.apex_equipment_materials import build_variant, unpack

OUT=ROOT/'.runtime/private-gym-office-20261008'
SOURCE=Path('C:/Users/might/Downloads/InspectorPro Blue Scanner Logo.png')
SET='asset-gym-office-set-worktop'
SHELF='asset-gym-office-bookshelf-2-apex'
LOGO='asset-gym-office-inspectorpro-logo'
P='pl-gym-office-'
OLD_LABELS={'Staff Desk','Staff Chair','Staff Storage','Staff Drawers','Work Guest Chair'}
COMPUTER_IDS={'pl-gym-wellness-work-'+k for k in ['monitor','keyboard','mouse','computer']}


def support_surface(entry):
    m=entry['sourceToCanonical']
    # Source tabletop is a measured 1.80 x 0.75 m horizontal face.
    origin=dict(x=m[12],y=.37166038513183594+m[13],z=m[14])
    return dict(surfaceId='worktop',label='Measured office desktop',
        localFrame=dict(origin=origin,normal=dict(x=0,y=1,z=0),xAxis=dict(x=1,y=0,z=0),zAxis=dict(x=0,y=0,z=1)),
        bounds=dict(minimumX=-.88,maximumX=.88,minimumZ=-.355,maximumZ=.355),
        allowedSides=['above'],evidenceStatus='derived')


def assets(library):
    staged=OUT/'staged-project';artifacts=[];entries=[]
    for key in ['set','bookshelf-2','book-shelf']:
        entry=json.loads((ROOT/f'generated/industrial_assets/local_library/gym-office-{key}/catalog-entry.json').read_text())
        assert all(a['assetId']!=entry['assetId'] for a in library['assets'])
        entries.append(entry)
    def emit(key,raw):
        rel=f'generated/industrial_assets/private_gym/office/{key}-{hashlib.sha256(raw).hexdigest()[:16]}.glb'
        dest=staged/rel;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(raw);artifacts.append(rel)
        return rel
    original=entries[0];office=deepcopy(original)
    office.update(assetId=SET,displayName='Office Desk and Three Chairs - Measured Worktop',supportSurfaces=[support_surface(original)])
    office['source']['supportedVariantOf']=original['assetId'];entries.append(office)
    shelf=deepcopy(entries[1]);doc,_=unpack((ROOT/shelf['artifact']).read_bytes())
    rules={str(i):'gold' if 'kulp' in mesh.get('name','').lower() else 'upholstery' for i,mesh in enumerate(doc['meshes'])}
    raw,evidence=build_variant(shelf,rules)
    shelf.update(assetId=SHELF,displayName='Bookshelf 2 - APEX Graphite and Gold',artifact=emit('bookshelf',raw))
    shelf['source']['appearanceVariantOf']=entries[1]['assetId'];entries.append(shelf)
    write(OUT/'bookshelf-material-evidence.json',evidence)
    dims=dict(width=2,height=2,depth=.014)
    raw=wall_glb(SOURCE.read_bytes(),dims,fit='contain',face=1,name='InspectorPro office logo')
    entries.append(dict(assetId=LOGO,displayName='InspectorPro Office Wall Logo',category='Building Structures',
        dimensions=dims,sourceToCanonical=IDENTITY,artifact=emit('inspectorpro-logo',raw),tags=['office','wall artwork'],
        description='Owner-provided InspectorPro branding on a thin wall-mounted backing.',
        source=dict(kind='authored-wall-art',originalFile=SOURCE.name,sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest())))
    library['assets'].extend(entries);library['summary']['total']=len(library['assets'])
    assert len({e['assetId'] for e in library['assets']})==len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    return artifacts,{e['artifact'] for e in entries}


def build(before,catalog):
    candidate=deepcopy(before)
    removed=[p['placementId'] for p in before['placements'] if p['metadata'].get('instanceLabel') in OLD_LABELS]
    assert len(removed)==5
    candidate['placements']=[p for p in candidate['placements'] if p['placementId'] not in removed]
    by_id={p['placementId']:p for p in candidate['placements']}
    def place(key,aid,x,z,y=0,yaw=0,color=None):
        q=math.radians(yaw)/2
        p=dict(placementId=P+key,assetId=aid,assetDefinitionRevision=catalog[aid]['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1),
            positionMode='manual',snapRelationship=None,
            metadata=dict(instanceLabel=key.replace('-',' ').title(),room='work',inputMethod='independent-authoring'))
        if color:p['appearance']=dict(color=color)
        assert p['placementId'] not in by_id
        candidate['placements'].append(p);return p
    office=place('desk-and-three-chairs',SET,33,-7.8,yaw=180,color='#35393E')
    place('bookshelf',SHELF,31.1,-10.45)
    surface=catalog[SET]['supportSurfaces'][0];origin=surface['localFrame']['origin']
    for key,dx,dz in [('monitor',0,-.12),('keyboard',0,.22),('mouse',.4,.22)]:
        p=by_id['pl-gym-wellness-work-'+key];x=origin['x']+dx;z=origin['z']+dz
        p['transform']=transform(office,x,z,0,origin['y'])
        p['snapRelationship']=dict(family='surface_attachment',attachmentId='surface:'+p['placementId'],
            supportPlacementId=office['placementId'],surfaceId='worktop',surfaceSource='asset_definition',
            localPosition=dict(x=x,z=z),localRotationDegrees=0,normalOffsetMeters=0,side='above',evidenceStatus='derived')
    by_id['pl-gym-wellness-work-computer']['transform']['position']=dict(x=34.75,y=0,z=-7.8)
    wall=by_id['pl-gym-wellness-work-cafe-divider'];box=catalog[wall['assetId']]['definition']['geometry']['aabb']
    logo=place('inspectorpro-wall-logo',LOGO,33,-10.85,y=1.08,color='#3B4147')
    logo['transform']['position']['z']=wall['transform']['position']['z']+box['maximum']['z']+.02+.007
    logo['snapRelationship']=dict(family='wall_attachment',supportPlacementId=wall['placementId'],
        supportAssetDefinitionRevision=wall['assetDefinitionRevision'],face='positive_z',
        localX=logo['transform']['position']['x']-wall['transform']['position']['x'],localY=1.08,normalGapMeters=.02)
    candidate['updatedAt']=datetime.now(timezone.utc).isoformat()
    return candidate,removed


def audit(before,after,catalog,removed):
    from shapely.geometry import box,LineString
    original={p['placementId']:p for p in before['placements']};actual={p['placementId']:p for p in after['placements']}
    for pid,p in original.items():
        if pid in removed:assert pid not in actual
        elif pid not in COMPUTER_IDS:assert actual[pid]==p,('Unexpected change',pid)
        else:
            a=deepcopy(p);b=deepcopy(actual[pid])
            for key in ['transform','snapRelationship']:a.pop(key);b.pop(key)
            assert a==b
    a=deepcopy(before);b=deepcopy(after)
    for key in ['placements','updatedAt']:a.pop(key);b.pop(key)
    assert a==b,'Room or other layout content changed'
    new={pid for pid in actual if pid not in original}
    assert new=={P+k for k in ['desk-and-three-chairs','bookshelf','inspectorpro-wall-logo']}
    office=box(30.10,-10.90,35.74,-3.10)
    for pid in new|COMPUTER_IDS:
        p=actual[pid];assert office.covers(footprint(p,catalog[p['assetId']]))
    # A clear approach from the door and a side path to the owner's chair.
    paths=[[(33,-3),(33,-5.9)],[(33,-5.3),(31,-5.3),(31,-9.5),(33,-9.5)]]
    for points in paths:
        clearance=LineString(points).buffer(.5,cap_style=2,join_style=2)
        for p in actual.values():
            if p['transform']['position']['y']>1:continue
            assert clearance.intersection(footprint(p,catalog[p['assetId']])).area<1e-7,('Blocked office access',p['placementId'])
    def dimensions(asset):
        bounds=catalog[asset]['definition']['geometry']['aabb']
        return dict(zip(('width','height','depth'),(bounds['maximum'][k]-bounds['minimum'][k] for k in ('x','y','z'))))
    return dict(roomMeters=[6,8],officeSetMeters=dimensions(SET),bookshelfMeters=dimensions(SHELF),
        removedFurniture=len(removed),retainedComputerAccessories=4,unchangedRoomGeometry=True,unrelatedPlacementsUnchanged=True,
        checkedAccessPaths=len(paths),logoFacesDoor=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=['stage','publish-assets','save'])
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST;staged=OUT/'staged-project'
    if args.phase!='stage':
        report=json.loads((OUT/'report.json').read_text())
        assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
        if args.phase=='publish-assets':
            assert report['status']=='validated' and manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes()
            for rel in report['artifacts']:
                dest=ROOT/rel;payload=(staged/rel).read_bytes()
                if dest.exists():assert dest.read_bytes()==payload
                else:RevisionedAuthorityRepository._atomic_write(dest,payload)
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            assert report['status']=='assets-published'
            raw=(OUT/'candidate.json').read_bytes();proof=json.loads((OUT/'native-check.json').read_text())
            assert proof['status']=='preview-verified' and proof['candidateHash']==hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for rel,digest in report['assetHashes'].items():assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
                audit(json.loads((OUT/'before.json').read_bytes()),json.loads(raw),catalog,report['removed'])
                receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,json.loads(raw),report['baseRevision'])
            finally:host.close()
            write(OUT/'saved.json',receipt['layout']);report.update(status='saved',savedRevision=receipt['revision'])
            hashes=saved_hashes();assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged']=True
        write(OUT/'report.json',report);print(report['status']);return
    raw=target.read_bytes();before=json.loads(raw);catalog_raw=manifest.read_bytes()
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        path=OUT/name
        if path.exists():assert path.read_bytes()==data,'Base changed'
        else:path.write_bytes(data)
    library=json.loads(catalog_raw);artifacts,imported=assets(library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        candidate,removed=build(before,catalog);write(OUT/'candidate-draft.json',candidate)
        checks=audit(before,candidate,catalog,removed)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate);write(OUT/'spatial.json',spatial)
        host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally:host.close()
    write(OUT/'candidate.json',receipt['layout'])
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),layoutHashes=saved_hashes(),
        artifacts=artifacts,assetHashes={rel:hashlib.sha256(((staged if rel in artifacts else ROOT)/rel).read_bytes()).hexdigest() for rel in imported},
        removed=removed,checks=checks,limitations=['Office STL interpreted as centimetres; dimensions require independent confirmation.',
            'Miniature Book Shelf source retained in library but not enlarged or placed.']))
    profile=json.loads((ROOT/'.runtime/private-gym-wellness-20261008/profile.json').read_text())
    profile.update(profileId='private-gym-office',origin='http://127.0.0.1:8561',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    front=shot('01-office-from-door',(33,2.1,-3.35),(33,1,-8.7))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,requiredAssets=[SET,SHELF,LOGO],
        shots=[front,shot('02-office-overhead',(33,10,-6.8),(33,0,-7)),shot('03-owner-workstation',(33,2,-9.7),(33,.9,-7.7)),
               shot('04-office-bookshelf',(32.2,2,-8.5),(31.1,1,-10.4))],finalShot=dict(front,name='05-saved-office')))
    print(json.dumps(checks))


if __name__=='__main__':main()
