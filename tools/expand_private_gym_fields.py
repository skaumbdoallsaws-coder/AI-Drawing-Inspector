"""Stage and verify the soccer hall and outdoor training yard, then save exactly that review."""
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
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
if sys.version_info[:2] == (3,14):
    sys.path.insert(0,str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'))
sys.path.append(str(ROOT/'.runtime/model-import-20261002/mesh-dependencies'))
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write, saved_hashes
from tools.private_gym_reception_art import wall_glb
from tools.add_factory02_conference_rooms import box_glb
from tools.audit_independent_factory_layer2 import footprint
from tools.private_gym_field_geometry import soccer_markings, goal_glb, RULE_SOURCE

OUT=ROOT/'.runtime/private-gym-fields-20261008'
PREFIX='private-gym-fields-'
HALL=(0,34,42,62)
TURF=(44,40,82,72)
WALLS=[
    ('south-west',28.5,.25,6.2,14.55,34.15,0),
    ('south-east',10.5,.25,6.2,36.45,34.15,0),
    ('west',27.4,.25,6.2,.15,48,90),
    ('north',41.4,.25,6.2,21,61.85,0),
    ('east-south',2.5,.25,6.2,41.85,35.55,90),
    ('east-north',22.5,.25,6.2,41.85,50.45,90),
    ('training-support',8,.25,3,75,61,0),
]


def prepare_assets(library):
    staged=OUT/'staged-project'; artifacts=[]
    imports=json.loads((OUT/'inventory.json').read_text())
    for item in imports:
        entry=json.loads((ROOT/item['target']/'catalog-entry.json').read_text())
        assert not any(a['assetId']==entry['assetId'] for a in library['assets'])
        library['assets'].append(entry)
    logo=(Path('C:/Users/might/Downloads')/'Metallic Gold Wolf APEX Gym Logo.png').read_bytes()
    for key,w,d,h,*_ in WALLS:
        dimensions=dict(width=w,depth=d,height=h)
        raw=wall_glb(logo,dimensions,fit='contain',face=-1,name='APEX soccer hall') if key=='north' else box_glb(w,d,h)
        relative=f'generated/industrial_assets/private_gym/fields/{key}/model.glb'
        target=staged/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(raw)
        artifacts.append(relative)
        library['assets'].append(dict(assetId='asset-'+PREFIX+key,displayName='APEX '+key.replace('-',' ').title()+' Wall',
            category='Building Structures',dimensions=dimensions,sourceToCanonical=IDENTITY,artifact=relative,
            tags=['gym','wall','soccer'],source=dict(kind='authored-primitive',generator=Path(__file__).name),
            description='Architectural concept. Soccer hall is shown with its roof cut away, like the original gym.'))
    relative='generated/industrial_assets/private_gym/fields/soccer-goal/model.glb'
    target=staged/relative;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(goal_glb());artifacts.append(relative)
    library['assets'].append(dict(assetId='asset-'+PREFIX+'soccer-goal',displayName='Small-Sided Soccer Goal - 3 x 2 m',
        category='Facilities',dimensions=dict(width=3.16,height=2.08,depth=1.3),sourceToCanonical=IDENTITY,artifact=relative,
        tags=['soccer','goal','sports'],source=dict(kind='authored-primitive',generator='private_gym_field_geometry.py',reference=RULE_SOURCE),
        description='Dimensioned concept goal, 3 x 2 m clear opening. Net and anchorage require equipment/installation review; not a manufacturer CAD model.'))
    library['summary']['total']=len(library['assets']);write(staged/PRIVATE_ASSET_MANIFEST,library)
    return artifacts


def operations(before,catalog):
    ops=[]
    ground=deepcopy(before['extensions']['facilityGround'])
    for key,bounds,color in [('hall',HALL,'#277246'),('turf',TURF,'#387b43'),('connection',(0,30,60,34),'#aeb9b9'),
                             ('east-connection',(42,34,60,40),'#aeb9b9')]:
        x0,z0,x1,z1=bounds
        ground['surfaces'].append(dict(surfaceId=PREFIX+key,minX=x0,maxX=x1,minZ=z0,maxZ=z1,
            startElevation=0,endElevation=0,slopeAxis='x',color=color))
    ops.append(dict(op='set_ground',ground=ground))
    for key,label,bounds,color in [('soccer','Indoor Soccer - 32 x 18 m',HALL,'#499167'),
                                  ('turf','Outdoor Turf + Conditioning',TURF,'#669455'),
                                  ('link','Sports Connection',(0,30,60,34),'#acb9b9'),
                                  ('east-link','Turf Access',(42,34,60,40),'#acb9b9')]:
        x0,z0,x1,z1=bounds
        ops.append(dict(op='add_zone',zone=dict(zoneId='zn-'+PREFIX+key,label=label,zoneType='workcell',
            boundary=[dict(x=x0,z=z0),dict(x=x1,z=z0),dict(x=x1,z=z1),dict(x=x0,z=z1)],floorElevation=0,
            anchors=[],evidence=[],extensions=dict(style=dict(fillColor=color)))))
    placed={}

    def place(key,asset,x,z,yaw=0,y=0,color=None,role='equipment'):
        q=math.radians(yaw)/2
        p=dict(placementId='pl-'+PREFIX+key,assetId=asset,assetDefinitionRevision=catalog[asset]['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1),
            positionMode='manual',snapRelationship=None,metadata=dict(instanceLabel=key.replace('-',' ').title(),
                gymRole=role,inputMethod='independent-authoring'))
        if color:p['appearance']=dict(color=color)
        ops.append(dict(op='place_asset',placement=p));placed[key]=p
        return p

    for key,w,d,h,x,z,yaw in WALLS:
        place(key,'asset-'+PREFIX+key,x,z,yaw,color='#626c70' if key!='training-support' else '#45484b',role='architecture')
    place('west-match-goal','asset-'+PREFIX+'soccer-goal',4.39,48,90)
    place('east-match-goal','asset-'+PREFIX+'soccer-goal',37.61,48,270)
    place('match-ball','asset-gym-field-football',21,48,color='#ecefe6')
    for i,x in enumerate((12,21,30),1):
        place('players-bench-'+str(i),'asset-public-slat-bench',x,59.8,180,color='#c99b39')
    place('training-goal','asset-gym-field-goal',48.5,69,180,color='#ebeee8')
    place('drill-ball','asset-gym-field-football',48.5,65,color='#ecefe6')
    for i,x in enumerate((54,59,64),1):
        place('training-tire-'+str(i),'asset-gym-field-tire',x,56,color='#272a2b')
    place('wheel-station','asset-gym-field-rear-wheel',68,56,color='#34383a')
    for i,x in enumerate((69.5,73),1):
        place('conditioning-bike-'+str(i),'asset-gym-field-bike',x,67,180,color='#c99b39')
    place('flat-bench','asset-gym-expansion-flat-bench',77,67,90,color='#384249')
    place('pull-up-station','asset-gym-commercial-power-tower',57,66,180,color='#45484b')
    place('free-weight-bench','asset-gym-commercial-workout-bench',62,66,90,color='#45484b')
    place('dumbbell-storage','asset-gym-dumbbell-rack',64,70,180,color='#45484b')
    place('pickup','asset-gym-field-pickup',78,45,0,color='#bec5c2',role='vehicle')
    support=placed['training-support']; aid='asset-gym-field-wall-rack'
    a=catalog[support['assetId']]['definition']['geometry']['aabb'];b=catalog[aid]['definition']['geometry']['aabb']
    local_z=a['minimum']['z']-.01+b['minimum']['z']
    p=place('wall-mounted-rack',aid,75,61+local_z,180,color='#252b2e')
    p['snapRelationship']=dict(family='wall_attachment',supportPlacementId=support['placementId'],
        supportAssetDefinitionRevision=support['assetDefinitionRevision'],face='negative_z',localX=0,localY=0,normalGapMeters=.01)

    def mark(key,x,z,w,d,color,y=.018,rotation=0,text=''):
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-'+PREFIX+key,label=key.replace('-',' ').title(),
            markingType='floor_text' if text else 'solid_line',semanticRole='decorative',positionMode='manual',
            transform=dict(position=dict(x=x,y=y,z=z),rotationDegrees=rotation),width=w,depth=d,
            fillColor=color,strokeColor=color,opacity=1,text=text,evidence=[],metadata=dict(authoredIn=PREFIX))))
    for i in range(8):
        mark('pitch-stripe-'+str(i),7+4*i,48,4,18,'#388752' if i%2 else '#307948',y=.004)
    for item in soccer_markings():
        mark('soccer-'+item['key'],item['x'],item['z'],item['width'],item['depth'],'#f5f5ec',rotation=item['rotation'])
    mark('soccer-title',21,36.2,14,.6,'#ddcf9b',text='APEX | INDOOR SOCCER')
    mark('outdoor-title',61,41.2,13,.7,'#f0dba9',text='APEX | OUTDOOR TRAINING')
    for i in range(5):
        mark('lane-line-'+str(i),60,43+2*i,20,.06,'#f1ecd9')
    for i in range(5):
        x=50+5*i
        mark('lane-distance-'+str(i),x,47,.06,8,'#f1ecd9')
        mark('distance-text-'+str(i),x,52,1.2,.4,'#f1ecd9',text=str(5*i)+' m')
    for i,z in enumerate((44,46,48,50),1):
        mark('lane-number-'+str(i),49,z,.7,.6,'#f1ecd9',text=str(i))
    for key,x,z,w,d in [('rack-pad',75,57.8,9,6),('strength-pad',61,67.3,12,7.5)]:
        mark(key,x,z,w,d,'#394447',y=.003)
    mark('pickup-bay',78,45,7,9,'#767e79',y=.004)
    for x in (74.5,81.5):mark('bay-edge-'+str(x),x,45,.10,9,'#d9d4be')
    mark('bay-end',78,40.5,7,.10,'#d9d4be')
    paths=[('gym-to-soccer',[(30,29),(30,32),(30,38)],1.5),
           ('hall-to-yard',[(30,38),(46,38),(46,60),(73,60)],1.5),
           ('gym-to-yard',[(30,32),(58,32),(58,38),(46,38)],1.5)]
    for key,points,width in paths:
        ops.append(dict(op='add_aisle',routeId='rt-'+PREFIX+key,aisle=dict(label=key.replace('-',' ').title(),
            centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,aisleKind='pedestrian',direction='two_way',
            color='#b9ba9c',clearanceEvidenceStatus='unverified')))
    return ops,paths


def audit(before,after,catalog,paths):
    from shapely.geometry import LineString,box
    for field,key in [('placements','placementId'),('zones','zoneId'),('routes','routeId'),('floorMarkings','markingId')]:
        current={x[key]:x for x in after[field]}
        assert all(current[x[key]]==x for x in before[field]),'Existing '+field+' changed'
    assert before['extensions']['facilityPerimeterWalls']==after['extensions']['facilityPerimeterWalls']
    assert after['extensions']['facilityGround']['surfaces'][:3]==before['extensions']['facilityGround']['surfaces']
    old={p['placementId'] for p in before['placements']}
    added=[p for p in after['placements'] if p['placementId'] not in old]
    for key,points,width in paths:
        route=LineString(points).buffer(width/2,cap_style=2,join_style=2)
        for p in added:
            assert route.intersection(footprint(p,catalog[p['assetId']])).area<1e-6,(key,p['placementId'],'blocked walkway')
    pitch=box(5,39,37,57)
    for p in added:
        shape=footprint(p,catalog[p['assetId']])
        if p['metadata']['gymRole']=='architecture':
            assert pitch.distance(shape)>3,(p['placementId'],'soccer runoff')
    pickup=next(p for p in added if p['metadata']['gymRole']=='vehicle')
    assert box(74.5,40.5,81.5,49.5).covers(footprint(pickup,catalog[pickup['assetId']]))
    assert all(p['transform']['scale']==1 for p in added)
    return dict(originalPlacementsUnchanged=len(before['placements']),addedPlacements=len(added),
        newZones=4,pitchMeters=[32,18],outdoorTurfMeters=[38,32],minimumWallRunoffMeters=3,
        blockedAuthoredWalkways=0,sourceModelScalePreserved=True,pickupSeparatedFromTrainingLanes=True,
        originalWallsAndBrandingUnchanged=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=['stage','publish-assets','save']);args=parser.parse_args()
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST;staged=OUT/'staged-project'
    if args.phase!='stage':
        report=json.loads((OUT/'report.json').read_text())
        if args.phase=='save' and report['status']=='saved':
            assert json.loads(target.read_bytes())==json.loads((OUT/'saved.json').read_bytes());print('Already saved');return
        assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed during review'
        if args.phase=='publish-assets':
            assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes(),'Library changed'
            for relative in report['artifacts']:
                dest=ROOT/relative;assert not dest.exists()
                RevisionedAuthorityRepository._atomic_write(dest,(staged/relative).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            raw=(OUT/'candidate.json').read_bytes();native=json.loads((OUT/'native-check.json').read_text())
            assert native['status']=='preview-verified'
            assert native['candidateHash']==hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for relative,digest in report['assetHashes'].items():
                assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest()==digest,'Asset changed: '+relative
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,json.loads(raw),report['baseRevision'])
            finally:host.close()
            write(OUT/'saved.json',receipt['layout'])
            report.update(status='saved',savedRevision=receipt['revision'])
            after=saved_hashes();assert all(after[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged']=True
        write(OUT/'report.json',report);print(json.dumps(dict(status=report['status'])));return
    OUT.mkdir(parents=True,exist_ok=True)
    raw=target.read_bytes();before=json.loads(raw);catalog_raw=manifest.read_bytes()
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        snapshot=OUT/name
        if snapshot.exists():assert snapshot.read_bytes()==data,'Base changed'
        else:snapshot.write_bytes(data)
    library=json.loads(catalog_raw);artifacts=prepare_assets(library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops,paths=operations(before,catalog)
        candidate=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks=audit(before,candidate,catalog,paths)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally:host.close()
    write(OUT/'candidate.json',receipt['layout']);write(OUT/'operations.json',ops)
    imported=[json.loads((ROOT/i['target']/'catalog-entry.json').read_text())['artifact'] for i in json.loads((OUT/'inventory.json').read_text())]
    asset_hashes={rel:hashlib.sha256(((staged if rel in artifacts else ROOT)/rel).read_bytes()).hexdigest() for rel in artifacts+imported}
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),layoutHashes=saved_hashes(),
        artifacts=artifacts,assetHashes=asset_hashes,checks=checks,markingReference=RULE_SOURCE,
        limitations=['Architectural concept, not building, sports, accessibility or safety certification.',
                    'Indoor hall shown in roof-cutaway style, consistent with the existing gym.',
                    'Training goal is the supplied 1.6 x 1.15 m floorball CAD; match goals are separately authored 3 x 2 m concepts.',
                    'Outdoor equipment weather resistance, fall zones, anchorage and installation need supplier review.',
                    'Supplied Ford model contains the cab and chassis but no cargo bed; it is retained without inventing missing CAD.',
                    'Pickup is a static display/parking placement, not an authorized vehicle exercise.']))
    profile=json.loads((ROOT/'.runtime/private-gym-apex-centered-20261008/profile.json').read_text())
    profile.update(profileId='private-gym-fields',origin='http://127.0.0.1:8549',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()));write(OUT/'profile.json',profile)
    def shot(name,p,t):return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    overview=shot('01-sports-campus',(112,93,119),(41,0,36))
    required=['asset-'+PREFIX+'soccer-goal','asset-gym-field-pickup','asset-gym-field-tire','asset-gym-field-bike','asset-gym-field-wall-rack']
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],requiredAssets=required,
        shots=[overview,shot('02-indoor-soccer',(35,5,37),(18,1,49)),shot('03-soccer-goal',(12,2.6,45),(4.5,1,48)),
               shot('04-outdoor-turf',(87,35,77),(62,0,56)),shot('05-strength-yard',(67,3,54),(75,1,61)),
               shot('06-tires',(55,2.5,60),(59,0.5,56)),shot('07-pickup',(70,3.5,41),(78,1,45))],
        finalShot=dict(overview,name='08-saved-sports-campus')))
    print(json.dumps(dict(status='validated',checks=checks)))


if __name__=='__main__':main()
