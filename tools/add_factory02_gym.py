"""Stage and publish a furnished, branded employee gym without changing existing work."""
from copy import deepcopy
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from shapely.geometry import LineString,box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path,RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost,PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.add_factory02_conference_rooms import IDENTITY,box_glb
from tools.add_factory02_parking_office import boundary,hashes,write_json,verify_native_candidate
from tools.audit_independent_factory_layer2 import footprint
from tools.brand_factory02_walls import branded_glb
from tools.expand_factory02_lunchroom import rectangle_tiles

STORE=ROOT/'.runtime/facility-layout'
IMPORT=ROOT/'.runtime/gym-import-20261003'
LAYOUT='fl-independent-factory-20260928'
RELATIVE=Path('layouts/local/site-local/layouts')/(LAYOUT+'.json')
ROOM=(302,76,328,94)
HEIGHT=3.6
WALLS=[('west',(302,76,302.2,94),None),
       ('north',(302.22,76,327.78,76.2),1),
       ('south',(302.22,93.8,327.78,94),-1),
       ('east-left',(327.8,76,328,82.8),None),
       ('east-right',(327.8,85.2,328,94),None)]
EQUIPMENT=[
    ('leg-press-01','vertical-leg-press',305.3,79.3,0,'#718995'),
    ('leg-press-02','vertical-leg-press',310.4,79.3,0,'#718995'),
    ('squat-rack-01','multi-station',315.2,79.3,0,'#4d8991'),
    ('squat-rack-02','multi-station',319.8,79.3,0,'#4d8991'),
    ('multi-gym','multi-gym-stl',324.7,79.3,0,'#698592'),
    ('bench-press-01','bench-press',314.4,87.8,180,'#78949b'),
    ('bench-press-02','bench-press',318.9,87.8,180,'#78949b'),
    ('adjustable-bench','flat-bench',324.4,87.8,180,'#42848d'),
    ('power-rack-01','weight-rack',314.4,91.3,180,'#607b88'),
    ('power-rack-02','weight-rack',318.9,91.3,180,'#607b88'),
    ('x1000','x1000',324.4,91.3,180,'#85a958'),
    ('dumbbell-rack-01','dumbbell-rack',310.3,87.6,0,'#586c79'),
    ('dumbbell-rack-02','dumbbell-rack',310.3,91.3,0,'#586c79'),
]
ROUTES=[('annex-access',[(320.6,62.5),(331,62.5),(331,84),(326,84)],2),
        ('main-walkway',[(326,84),(303.5,84)],2)]


def prepare_assets(out,library):
    original=json.loads((IMPORT/'original-sources.json').read_text())
    for name,digest in original['hashes'].items():
        assert hashlib.sha256((Path(r'C:/Users/might/Downloads/gym')/name).read_bytes()).hexdigest()==digest
    entries=json.loads((IMPORT/'entries.json').read_text())
    assert len(entries)==8
    for a in entries:
        target=ROOT/a['artifact'];evidence=json.loads((target.parent/'thumbnail-evidence.json').read_text())
        assert evidence['passed'] and evidence['source']['sha256']==hashlib.sha256(target.read_bytes()).hexdigest()
    library['assets'].extend(entries);artifacts=[];branding={}
    for key,(x0,z0,x1,z1),face in WALLS:
        dimensions=dict(width=x1-x0,depth=z1-z0,height=HEIGHT)
        if face:
            data,branding[key]=branded_glb(dimensions,dict(width=8,centerX=0,centerY=2.65,face=face))
        else:data=box_glb(dimensions['width'],dimensions['depth'],HEIGHT)
        artifact=f'generated/industrial_assets/factory02_gym/{key}/model.glb'
        target=out/'staged-project'/artifact;target.parent.mkdir(parents=True);target.write_bytes(data)
        artifacts.append(artifact)
        library['assets'].append(dict(assetId='asset-factory02-gym-wall-'+key,
            displayName='Gym '+key.title()+' Wall'+(' - InspectorPro' if face else ''),
            category='Building Structures',artifact=artifact,dimensions=dimensions,sourceToCanonical=IDENTITY,
            description='Authored gym concept partition; construction and fire rating unverified.',tags=['wall','gym','perimeter'],
            source=dict(kind='authored-primitive',generator=Path(__file__).name)))
    assert len({a['assetId'] for a in library['assets']})==len(library['assets'])
    library['summary']['total']=len(library['assets'])
    return artifacts,branding


def operations(catalog):
    ops=[]
    def zone(key,label,b,color):
        ops.append(dict(op='add_zone',zone=dict(zoneId='zn-gym-'+key,label=label,zoneType='workcell',
            boundary=boundary(b),floorElevation=0,anchors=[],evidence=[],extensions=dict(style=dict(fillColor=color)))))
    def paint(key,b,color,text=''):
        x0,z0,x1,z1=b
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-gym-'+key,
            markingType='floor_text' if text else 'solid_line',label=key.replace('-',' ').title(),semanticRole='decorative',
            transform=dict(position=dict(x=(x0+x1)/2,y=.01 if text else .003,z=(z0+z1)/2),rotationDegrees=0),
            width=x1-x0,depth=z1-z0,fillColor=color,strokeColor=color,opacity=1,text=text,
            positionMode='manual',metadata=dict(authoredIn='gym_extension'),evidence=[])))
    def place(key,aid,x,z,yaw,color,locked=False):
        q=math.radians(yaw)/2;a=catalog[aid]
        ops.append(dict(op='place_asset',placement=dict(placementId='pl-gym-'+key,assetId=aid,
            assetDefinitionRevision=a['assetDefinitionRevision'],positionMode='locked' if locked else 'manual',
            snapRelationship=None,appearance=dict(color=color),metadata=dict(instanceLabel=key.replace('-',' ').title(),inputMethod='independent-authoring'),
            transform=dict(position=dict(x=x,y=0,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1))))
    zone('room','Employee Gym - 468 m2',ROOM,'#a5c4c7')
    zone('access','Gym Access Corridor',(329.8,61.5,332.2,85.2),'#bdd1d5')
    for key,(x0,z0,x1,z1),_ in WALLS:
        place('wall-'+key,'asset-factory02-gym-wall-'+key,(x0+x1)/2,(z0+z1)/2,0,'#e1e8e6',True)
    for key,slug,x,z,yaw,color in EQUIPMENT:place(key,'asset-gym-'+slug,x,z,yaw,color)
    clear=unary_union([LineString(p).buffer(w/2,cap_style=2,join_style=2) for _,p,w in ROUTES])
    mats=[(x-.5,z-.9,x+.5,z+.9) for x in (304,306.5) for z in (87,89.5,92)]
    # The tiler needs individual rectangular segments, not the bounding box of
    # an L-shaped union, which would omit otherwise usable floor patches.
    segments=[LineString([a,b]).buffer(width/2,cap_style=2) for _,points,width in ROUTES for a,b in zip(points,points[1:])]
    for i,b in enumerate(rectangle_tiles((302.2,76.2,327.8,93.8),segments+[box(*b) for b in mats])):
        paint('rubber-floor-'+str(i),b,'#3f4b50')
    for i,b in enumerate(mats):paint('stretch-mat-'+str(i+1),b,'#398894')
    paint('strength-label',(310,76.5,320,77.05),'#d8efef','STRENGTH TRAINING')
    paint('stretch-label',(302.6,85.3,307.8,85.7),'#d8efef','STRETCHING')
    paint('freeweights-label',(313,85.3,326,85.7),'#d8efef','FREE WEIGHTS')
    for key,points,width in ROUTES:
        ops.append(dict(op='add_aisle',routeId='rt-gym-'+key,aisle=dict(label=key.replace('-',' ').title(),
            centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,aisleKind='pedestrian',
            direction='two_way',color='#62becb',clearanceEvidenceStatus='unverified')))
    return ops


def audit(before,after,catalog):
    expected=deepcopy(after)
    for field,key,prefix in [('placements','placementId','pl-gym-'),('zones','zoneId','zn-gym-'),
        ('routes','routeId','rt-gym-'),('floorMarkings','markingId','fm-gym-')]:
        expected[field]=[p for p in after[field] if not p[key].startswith(prefix)]
    expected['updatedAt']=before['updatedAt'];assert expected==before,'Unrelated layout content changed'
    added=[p for p in after['placements'] if p['placementId'].startswith('pl-gym-')]
    assert len(added)==len(EQUIPMENT)+len(WALLS)
    assert {p['assetId'] for p in added if p['assetId'].startswith('asset-gym-')}=={'asset-gym-'+e[1] for e in EQUIPMENT}
    shapes={p['placementId']:footprint(p,catalog[p['assetId']]) for p in after['placements']}
    clear=unary_union([LineString(points).buffer(width/2,cap_style=2,join_style=2) for _,points,width in ROUTES])
    assert clear.is_valid and clear.geom_type=='Polygon'
    for p in added:
        shape=shapes[p['placementId']]
        assert shape.intersection(clear).area<1e-7,('Blocked corridor',p['placementId'])
        for other in after['placements']:
            if other['placementId']!=p['placementId']:
                assert shape.intersection(shapes[other['placementId']]).area<1e-7,('Overlap',p['placementId'],other['placementId'])
    # This is a concept spacing allowance, not an operating-clearance certification.
    envelopes={p['placementId']:shapes[p['placementId']].buffer(.6,join_style=2) for p in added if p['assetId'].startswith('asset-gym-')}
    for key,shape in envelopes.items():
        assert box(302.2,76.2,327.8,93.8).covers(shape),(key,'Allowance leaves room')
        assert shape.intersection(clear).area<1e-7,(key,'Allowance blocks walkway')
        for other,value in envelopes.items():
            if key!=other:assert shape.intersection(value).area<1e-7,(key,other,'Allowances overlap')
    return dict(existingPlacementsPreserved=len(before['placements']),gymEquipment=len(EQUIPMENT),
        sourceModelTypes=8,brandedWalls=2,roomAreaM2=468,conceptSpacingMeters=.6,
        operatingClearancesQualified=False,corridorConnected=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--publish-assets',action='store_true')
    parser.add_argument('--publish-layout',action='store_true')
    parser.add_argument('--native-report',type=Path)
    args=parser.parse_args();out=args.output.resolve();target=STORE/RELATIVE;manifest=ROOT/PRIVATE_ASSET_MANIFEST
    if args.publish_assets or args.publish_layout:
        report=json.loads((out/'report.json').read_text());staged=out/'staged-project'
        assert target.read_bytes()==(out/'before.json').read_bytes(),'Saved Factory 02 changed'
        assert hashes(target.parent)==report['layoutHashes'],'Saved layouts changed'
        if args.publish_assets:
            assert report['status']=='validated' and manifest.read_bytes()==(out/'catalog-before.json').read_bytes()
            for artifact in report['artifacts']:
                dest=ROOT/artifact;assert not dest.exists();dest.parent.mkdir(parents=True,exist_ok=True)
                RevisionedAuthorityRepository._atomic_write(dest,(staged/artifact).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            assert report['status']=='assets-published' and args.native_report
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for artifact in report['artifacts']:assert (ROOT/artifact).read_bytes()==(staged/artifact).read_bytes()
            candidate=json.loads((out/'candidate.json').read_text())
            verify_native_candidate(json.loads(args.native_report.read_text()),candidate,(out/'validation-store'/RELATIVE).read_bytes())
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                audit(json.loads((out/'before.json').read_text()),candidate,{a['assetId']:a for a in host.authoritative_asset_catalog()})
                saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            finally:host.close()
            others=lambda values:{k:v for k,v in values.items() if k!=target.name}
            assert others(hashes(target.parent))==others(report['layoutHashes'])
            write_json(out/'saved.json',saved['layout']);report.update(status='saved',savedRevision=saved['revision'],otherLayoutsUnchanged=True)
    else:
        raw=target.read_bytes();before=json.loads(raw)
        assert not any(p['placementId'].startswith('pl-gym-') for p in before['placements'])
        out.mkdir(parents=True,exist_ok=False);(out/'before.json').write_bytes(raw)
        (out/'catalog-before.json').write_bytes(manifest.read_bytes());library=json.loads(manifest.read_text())
        artifacts,branding=prepare_assets(out,library);write_json(out/'staged-project'/PRIVATE_ASSET_MANIFEST,library)
        stage=out/'validation-store'
        copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'))
        copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'))
        host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=out/'staged-project')
        try:
            catalog={a['assetId']:a for a in host.authoritative_asset_catalog()};ops=operations(catalog)
            base=layout_revision(before);candidate=apply_facility_layout_operations(before,ops,base_revision=base)['document']
            checks=audit(before,candidate,catalog)
            spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
            write_json(out/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
            assert not any(f['code'] in {'aisle_obstructed','placement_collision','zone_containment_violation','placement_outside_floor'}
                and any(s.startswith(('pl-gym-','rt-gym-')) for s in f['subjectRefs']) for f in spatial['findings']), 'Gym geometry warning'
            saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,base)
            write_json(out/'candidate.json',saved['layout']);write_json(out/'operations.json',ops)
            report=dict(status='validated',baseRevision=base,candidateRevision=saved['revision'],checks=checks,
                layoutHashes=hashes(target.parent),artifacts=artifacts,branding=branding,
                placementCount=len(candidate['placements']),limitations=['Concept only: egress, structural loads, ventilation, acoustics and operating clearances need engineering review.','Unitless STL scale inferred as millimetres.'])
        finally:host.close()
    write_json(out/'report.json',report)
    print(json.dumps({k:report[k] for k in ('status','placementCount','checks')}))


if __name__=='__main__':main()
