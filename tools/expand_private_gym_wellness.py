"""Stage the APEX work/lounge and five-person wellness extension for native review."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree, copy2
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools'),str(Path.home()/'AppData/Roaming/Python/Python314/site-packages'),
              str(ROOT/'.runtime/model-import-20261002/mesh-dependencies')]
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write, saved_hashes
from tools.private_gym_reception_art import wall_glb
from tools.add_factory02_conference_rooms import box_glb
from tools.audit_independent_factory_layer2 import footprint
from tools.equip_factory02_cubicles import transform
from tools.apex_equipment_materials import build_variant, unpack

OUT=ROOT/'.runtime/private-gym-wellness-20261008'
IMPORT=ROOT/'.runtime/private-gym-wellness-import-20261008'
PREFIX='gym-wellness-'
P='pl-'+PREFIX
ROOMS={
    'lounge':('APEX Social Lounge',(0,-18,22,-3),'#40464c'),
    'conference':('Conference - 8 Seats',(22,-11,30,-3),'#434a50'),
    'work':('Private Workspace',(30,-11,36,-3),'#434a50'),
    'kitchen':('Kitchenette',(22,-18,28,-11),'#6b7277'),
    'cafe':('Cafe - 8 Seats',(28,-18,36,-11),'#535c62'),
    'corridor':('Work + Social Connection',(0,-3,36,0),'#777e83'),
    'recovery':('Recovery - 5 Stations',(54,0,60,10),'#454c51'),
    'bath':('Private Washrooms - 5 Bays',(51,12,60,22),'#676e73'),
    'changing':('Lockers + Changing - 5 People',(51,22,60,30),'#515a61'),
}
MOVED={'Staff Desk','Staff Chair','Staff Storage','Staff Drawers','Changing Bench 1','Changing Bench 2',
       'Towel Cabinet 1','Towel Cabinet 2','Wash Bench'}
REMOVED={'Wash Sink 1','Wash Sink 2'}
THEMED=['unknown-seat','massage-chair','massage-table','arcade','sideboard','sofa','foosball-native',
        'folding-pingpong','bathtub','vanity','showerhead','locker','toilet']


def aid(key):return 'asset-'+PREFIX+key+'-apex'


def material_rules(key,entry):
    doc,_=unpack((ROOT/entry['artifact']).read_bytes())
    rules={}
    for i,m in enumerate(doc['meshes']):
        name=m.get('name','').lower()
        role='frame'
        if key in {'unknown-seat','sofa','massage-chair'}:role='upholstery'
        if key=='massage-table':
            role='upholstery' if any(s in name for s in ['\u0442\u0440\u044f\u043f','\u043f\u043e\u0434\u0443\u0448','\u0434\u0441\u043f','\u0444\u043e\u043d\u0435\u0440']) else 'frame'
            if any(s in name for s in ['screw','washer','nut','bolt']):role='steel'
        if key in {'toilet','bathtub'}:role='marking'
        if key=='showerhead':role='gold'
        if key=='vanity':
            role='frame'
            if any(s in name for s in ['top','sink','counter']):role='marking'
            if any(s in name for s in ['handle','faucet','tap','knob']):role='gold'
            if 'mirror' in name:role='steel'
        if key=='locker' and any(s in name for s in ['handle','lock','hinge','key']):role='gold'
        rules[str(i)]=role
    if key=='vanity':rules.update({'0:0':'frame','0:1':'gold','0:2':'steel','0:3':'marking','3:0':'frame','3:1':'steel'})
    regions=[]
    def region(lo,hi,role):regions.append(dict(bounds=[lo,hi],role=role))
    if key in {'sofa','unknown-seat'}:
        region([-5,0,-5],[5,.13,5],'frame')
    if key=='massage-chair':
        region([-5,0,-5],[5,.18,5],'frame')
    if key=='arcade':
        region([-.5,1.05,-1],[.5,1.15,1],'gold')
        region([-.5,1.8,-1],[.5,2.0,1],'gold')
        region([-.42,1.15,.12],[.42,1.75,.6],'smoked_glass')
    if key=='folding-pingpong':
        region([-5,.72,-5],[5,.8,5],'upholstery')
        region([-5,.8,-5],[5,2,5],'marking')
        region([-5,.70,-5],[5,.73,5],'gold')
    if key=='foosball-native':
        region([-5,.68,-5],[5,.82,5],'gold')
        region([-.61,.72,-.32],[.61,.82,.32],'upholstery')
    if key=='locker':region([-5,1.70,-5],[5,1.76,5],'gold')
    if key=='sideboard':
        region([-5,.1,-5],[5,.18,5],'gold')
        region([-5,1.89,-5],[5,2,5],'gold')
    if regions:rules['regions']=regions
    return rules


def theme_assets():
    entries=[]
    for key in THEMED:
        original=json.loads((ROOT/f'generated/industrial_assets/local_library/gym-wellness-{key}/catalog-entry.json').read_text())
        folder=ROOT/f'generated/industrial_assets/private_gym/wellness/{key}'
        folder.mkdir(parents=True,exist_ok=True)
        # Dedicated source copy ensures concept scaling is preserved by the material batcher.
        source=folder/'model.glb';source.write_bytes((ROOT/original['artifact']).read_bytes())
        temp=deepcopy(original);temp['artifact']=source.relative_to(ROOT).as_posix()
        payload,evidence=build_variant(temp,material_rules(key,original))
        artifact=folder/'apex.glb';artifact.write_bytes(payload)
        entry=deepcopy(original)
        entry.update(assetId=aid(key),displayName=original['displayName']+' - APEX',artifact=artifact.relative_to(ROOT).as_posix())
        entry['source']=dict(original['source'],appearanceVariantOf=original['assetId'])
        entry['appearanceEvidence']=dict(geometryPreserved=True,sourceSha256=evidence['sourceSha256'])
        write(folder/'material-evidence.json',evidence);write(folder/'catalog-entry.json',entry)
        entries.append(entry)
        print(json.dumps(dict(assetId=entry['assetId'],drawGroups=evidence['drawGroups'])),flush=True)
    write(IMPORT/'apex-entries.json',entries)


def wall_specs():
    # Each tuple is a physical segment; deliberate gaps are the doors.
    specs=[
        ('lounge-west',.24,15,3.2,.12,-10.5),
        ('corridor-west',.24,3,3.2,.12,-1.5),
        ('annex-east',.24,18,3.2,35.88,-9),
        ('annex-front-left',5,.24,3.2,2.5,-17.88),
        ('annex-front-right',29,.24,3.2,21.5,-17.88),
        ('lounge-north-left',5,.18,3.2,2.5,-3),
        ('lounge-north-right',15,.18,3.2,14.5,-3),
        ('conf-north-left',3.2,.18,3.2,23.6,-3),
        ('conf-north-right',3.2,.18,3.2,28.4,-3),
        ('work-north-left',2.2,.18,3.2,31.1,-3),
        ('work-north-right',2.2,.18,3.2,34.9,-3),
        ('lounge-east-upper',.18,8,3.2,22,-7),
        ('lounge-east-lower',.18,2,3.2,22,-17),
        ('lounge-east-middle',.18,2,3.2,22,-12),
        ('meeting-work-divider',.18,8,3.2,30,-7),
        ('meeting-cafe-divider',8,.18,3.2,26,-11),
        ('work-cafe-divider',6,.18,3.2,33,-11),
        ('wash-front',8.6,.15,2.8,55.6,12.15),
    ]
    for i in range(6):specs.append((f'bay-divider-{i}',.10,4.4,2.25,51.5+1.65*i,14.4))
    for i in range(5):
        center=52.325+1.65*i
        specs.extend([(f'bay-front-{i}-left',.275,.1,2.25,center-.6875,16.6),
                      (f'bay-front-{i}-right',.275,.1,2.25,center+.6875,16.6),
                      (f'bay-open-door-{i}',.03,1.06,2.05,center-.575,16.02)])
    from shapely.geometry import box
    result=[];occupied=[]
    for key,w,d,h,x,z in specs:
        bounds=(x-w/2,z-d/2,x+w/2,min(z+d/2,-.12) if key in {'annex-east','corridor-west'} else z+d/2)
        x0,z0,x1,z1=bounds
        # All authored junctions meet segment ends. Trim to butt joints, retaining a rectangular collision envelope.
        for previous in occupied:
            obstacle=previous.buffer(.012,join_style=2)
            if not box(x0,z0,x1,z1).intersects(obstacle):continue
            a,b,c,e=obstacle.bounds
            if w>=d:
                if (a+c)/2<x:x0=max(x0,c)
                else:x1=min(x1,a)
            else:
                if (b+e)/2<z:z0=max(z0,e)
                else:z1=min(z1,b)
        assert (x1-x0)*(z1-z0)>w*d*.55,(key,'Unexpected wall cut')
        x0+=.006;z0+=.006;x1-=.006;z1-=.006
        result.append((key,x1-x0,z1-z0,h,(x0+x1)/2,(z0+z1)/2))
        occupied.append(box(x0,z0,x1,z1))
    return result


def prepare_assets(library):
    staged=OUT/'staged-project';artifacts=[]
    def artifact(group,key,payload):
        digest=hashlib.sha256(payload).hexdigest()
        rel=f'generated/industrial_assets/private_gym/wellness/{group}/{key}-{digest[:16]}.glb'
        dest=staged/rel;dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(payload);artifacts.append(rel)
        return rel
    imported=[]
    for item in json.loads((IMPORT/'inventory.json').read_text()):
        entry=json.loads((ROOT/item['target']/'catalog-entry.json').read_text())
        imported.append(entry)
    imported+=json.loads((IMPORT/'apex-entries.json').read_text())
    old={a['assetId'] for a in library['assets']}
    assert not old.intersection(a['assetId'] for a in imported)
    library['assets'].extend(imported)
    # The source showerhead is combined with an explicit floor-supported riser.
    import numpy as np
    import trimesh
    from io import BytesIO
    head=next(e for e in imported if e['assetId']==aid('showerhead'))
    scene=trimesh.load_scene(ROOT/head['artifact'],process=False)
    canonical=np.asarray(head['sourceToCanonical']).reshape(4,4,order='F')
    rotation=trimesh.transformations.rotation_matrix(math.radians(270),[0,1,0])
    rotation[:3,3]=[0,2.08,.215]
    scene.apply_transform(rotation@canonical)
    post=trimesh.load_scene(BytesIO(box_glb(.07,.07,2.3)),file_type='glb',process=False)
    for node in post.graph.nodes_geometry:
        matrix,name=post.graph[node];mesh=post.geometry[name].copy();mesh.apply_transform(matrix)
        scene.add_geometry(mesh,node_name='Authored shower riser')
    lo,hi=scene.bounds;matrix=np.eye(4);matrix[:3,3]=[-(lo[0]+hi[0])/2,-lo[1],-(lo[2]+hi[2])/2]
    rel=artifact('furniture','shower-assembly',scene.export(file_type='glb'))
    library['assets'].append(dict(assetId='asset-'+PREFIX+'shower-assembly',displayName='APEX Shower with Floor Riser',
        category='Facilities',description='Supplied showerhead on authored concept riser; plumbing and installation are unqualified.',
        artifact=rel,dimensions=dict(zip(('width','height','depth'),(hi-lo).tolist())),sourceToCanonical=matrix.flatten(order='F').tolist(),
        tags=['gym','shower'],source=dict(kind='authored-assembly',headSource=head['assetId'])))
    logo=(ROOT/'generated/industrial_assets/private_gym/apex-court/back/branding-only/centered/apex-logo.png').read_bytes()
    for key,w,d,h,x,z in wall_specs():
        dims=dict(width=w,depth=d,height=h)
        # Keep branding clear of the presentation screen and facing the lounge.
        raw=wall_glb(logo,dims,fit='contain',face=1,name='APEX work and wellness') if key=='annex-front-left' else box_glb(w,d,h)
        rel=artifact('walls',key,raw)
        library['assets'].append(dict(assetId='asset-'+PREFIX+key,displayName='APEX '+key.replace('-',' ').title(),
            category='Building Structures',artifact=rel,dimensions=dims,sourceToCanonical=IDENTITY,
            description='Authored APEX concept partition. Dimensions and door gaps are explicit; building compliance is not qualified.',
            tags=['wall','gym','wellness'],source=dict(kind='authored-primitive',generator=Path(__file__).name)))
    # Authored furniture is identified as such rather than represented as supplied CAD.
    for key,w,d,h in [('coffee-table',1.1,.65,.42),('shower-tray',1.2,1.2,.04),('shower-post',.07,.07,2.3),
                       ('chess-plinth',1.1,1.1,.73)]:
        rel=artifact('furniture',key,box_glb(w,d,h))
        e=dict(assetId='asset-'+PREFIX+key,displayName='APEX '+key.replace('-',' ').title(),category='Facilities',
            artifact=rel,dimensions=dict(width=w,depth=d,height=h),sourceToCanonical=IDENTITY,
            description='Dimensioned concept furniture or fixture support, not manufacturer CAD.',
            tags=['gym','concept furniture'],source=dict(kind='authored-primitive',generator=Path(__file__).name))
        if key=='chess-plinth':e['supportSurfaces']=[dict(surfaceId='top',label='Game tabletop',
            localFrame=dict(origin=dict(x=0,y=h,z=0),normal=dict(x=0,y=1,z=0),xAxis=dict(x=1,y=0,z=0),zAxis=dict(x=0,y=0,z=1)),
            bounds=dict(minimumX=-.54,minimumZ=-.54,maximumX=.54,maximumZ=.54),allowedSides=['above'],evidenceStatus='derived')]
        library['assets'].append(e)
    library['summary']['total']=len(library['assets'])
    assert len({a['assetId'] for a in library['assets']})==len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    return artifacts,[e['artifact'] for e in imported]


def operations(before,catalog):
    ops=[];details=dict(moved=[],removed=[],doors=[],capacities=dict(recovery=5,changing=5,washBays=5,conference=8,cafe=8))
    ground=deepcopy(before['extensions']['facilityGround'])
    for key in ['lounge','conference','work','kitchen','cafe','corridor']:
        label,(x0,z0,x1,z1),color=ROOMS[key]
        ground['surfaces'].append(dict(surfaceId=PREFIX+key,minX=x0,maxX=x1,minZ=z0,maxZ=z1,
            startElevation=0,endElevation=0,slopeAxis='x',color=color))
    ops.append(dict(op='set_ground',ground=ground))
    walls=deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    walls['openings'].append(dict(edge=0,startMeters=20.4,endMeters=21.8))
    walls['openings'].sort(key=lambda opening:(opening['edge'],opening['startMeters']))
    ops.append(dict(op='set_perimeter_walls',wallSettings=walls))
    ops.append(dict(op='add_zone',zone=dict(zoneId='zn-'+PREFIX+'annex',label='APEX Work + Social Annex',zoneType='workcell',
        boundary=[dict(x=0,z=-18),dict(x=36,z=-18),dict(x=36,z=0),dict(x=0,z=0)],floorElevation=0,
        anchors=[],evidence=[],extensions=dict(style=dict(fillColor='#40464c')))))
    for key,(label,b,color) in ROOMS.items():
        if key=='recovery':
            old=next(z for z in before['zones'] if z['label'].startswith('Staff + Storage'))
            zone=deepcopy(old);zone['label']=label
            ops.append(dict(op='edit_zone',zoneId=zone['zoneId'],patch=dict(label=label)))
            continue
        x0,z0,x1,z1=b
        ops.append(dict(op='add_zone',zone=dict(zoneId='zn-'+PREFIX+key,label=label,zoneType='workcell',
            boundary=[dict(x=x0,z=z0),dict(x=x1,z=z0),dict(x=x1,z=z1),dict(x=x0,z=z1)],floorElevation=0,
            anchors=[],evidence=[],extensions=dict(style=dict(fillColor=color)))))
    placed={}
    def place(key,asset,x,z,yaw=0,y=0,color=None,role='equipment',room=None):
        a=catalog[asset];q=math.radians(yaw)/2
        p=dict(placementId=P+key,assetId=asset,assetDefinitionRevision=a['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1),
            positionMode='manual',snapRelationship=None,metadata=dict(instanceLabel=key.replace('-',' ').title(),
                gymRole=role,room=room,inputMethod='independent-authoring'))
        if color:p['appearance']=dict(color=color)
        ops.append(dict(op='place_asset',placement=p));placed[key]=p;return p
    def move(label,x,z,yaw=0):
        p=deepcopy(next(p for p in before['placements'] if p['metadata'].get('instanceLabel')==label))
        details['moved'].append(p['placementId'])
        ops.extend([dict(op='move_placement',placementId=p['placementId'],position=dict(x=x,y=0,z=z),movementKind='user'),
                    dict(op='rotate_placement',placementId=p['placementId'],quaternion=dict(x=0,y=math.sin(math.radians(yaw)/2),z=0,w=math.cos(math.radians(yaw)/2)),movementKind='user')])
        p['transform']=transform(dict(transform=dict(position=dict(x=x,y=0,z=z),quaternion=dict(x=0,y=0,z=0,w=1))),0,0,yaw)
        placed[label]=p;return p
    def attach(key,asset,support,surface,x,z,yaw=0,color=None):
        s=next(s for s in catalog[support['assetId']]['supportSurfaces'] if s['surfaceId']==surface)
        p=place(key,asset,0,0,color=color,role='supported equipment')
        p['transform']=transform(support,x,z,yaw,s['localFrame']['origin']['y'])
        p['snapRelationship']=dict(family='surface_attachment',attachmentId='surface:'+p['placementId'],
            supportPlacementId=support['placementId'],surfaceId=surface,surfaceSource='asset_definition',
            localPosition=dict(x=x,z=z),localRotationDegrees=yaw,normalOffsetMeters=0,side='above',evidenceStatus='derived')
        return p
    def mark(key,b,color,text='',y=.014):
        x0,z0,x1,z1=b
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-'+PREFIX+key,label=key.replace('-',' ').title(),
            markingType='floor_text' if text else 'solid_line',semanticRole='decorative',positionMode='manual',
            transform=dict(position=dict(x=(x0+x1)/2,y=y,z=(z0+z1)/2),rotationDegrees=0),
            width=x1-x0,depth=z1-z0,fillColor=color,strokeColor=color,opacity=1,text=text,evidence=[],metadata={})))
    for label in REMOVED:
        pid=next(p['placementId'] for p in before['placements'] if p['metadata'].get('instanceLabel')==label)
        details['removed'].append(pid);ops.append(dict(op='delete_placement',placementId=pid))
    for key,w,d,h,x,z in wall_specs():
        place(key,'asset-'+PREFIX+key,x,z,y=2.10 if 'bay-header' in key else 0,
            color='#C99B39' if 'bay-header' in key else '#3B4147',role='architecture')
    for key in ['lounge','conference','work','kitchen','cafe']:
        label,(x0,z0,x1,z1),_=ROOMS[key]
        mark(key+'-label',(x0+.7,z0+.45,min(x1-.7,x0+8),z0+1.0),'#C99B39',label.upper())
    # Keep existing support floor tiles, replacing only their obsolete text labels.
    for m in before['floorMarkings']:
        if m['markingId'].endswith(('staff-label','wash-label','changing-label')):
            ops.append(dict(op='delete_floor_marking',markingId=m['markingId']))
    mark('recovery-label',(54.6,8.7,57.5,9.1),'#C99B39','RECOVERY | 5')
    mark('wash-label',(53.2,18.4,58.8,18.85),'#C99B39','PRIVATE WASHROOMS')
    mark('changing-label',(53,24,58.7,24.4),'#C99B39','LOCKERS + CHANGING')
    # Five private bays, with a 1.1 m concept door opening each.
    for i in range(5):
        x=52.325+1.65*i
        mark(f'bay-number-{i}',(x-.38,16.95,x+.38,17.3),'#C99B39',str(i+1))
        details['doors'].append(dict(name=f'Wash Bay {i+1}',bounds=[x-.55,16.3,x+.55,16.95]))
        if i<2:place(f'private-wc-{i+1}',aid('toilet'),x,13.1,90,room='bath')
        elif i<4:
            place(f'shower-tray-{i-1}','asset-'+PREFIX+'shower-tray',x,13.7,color='#8d969c',room='bath')
            place(f'shower-assembly-{i-1}','asset-'+PREFIX+'shower-assembly',x,12.76,room='bath')
        else:place('private-bath',aid('bathtub'),x,13.7,room='bath')
    place('double-vanity',aid('vanity'),55.8,21.55,180,room='bath')
    move('Wash Bench',58.5,19.7,90)
    # Six compartments per bank, including the source's open-door envelopes.
    for i,x in enumerate((54,57),1):place(f'locker-bank-{i}',aid('locker'),x,28.95,180,room='changing')
    move('Changing Bench 1',54,26,0);move('Changing Bench 2',56.8,26,0)
    place('changing-seat-5','asset-chair-black',58.8,25.8,color='#35393E',room='changing')
    move('Towel Cabinet 1',52,25.8,90);move('Towel Cabinet 2',59,28,270)
    for i,z in enumerate((2,4.5,7),1):place(f'recovery-chair-{i}',aid('massage-chair'),55.7,z,room='recovery')
    for i,z in enumerate((2.6,5.8),1):place(f'recovery-table-{i}',aid('massage-table'),58.5,z,room='recovery')
    place('recovery-towels','asset-hideaway-cabinet',55.8,8.9,180,color='#17191C',room='recovery')
    # Social lounge keeps a continuous clear path from the new entrance to reception.
    place('lounge-sofa-west',aid('sofa'),2.1,-6.4,90,room='lounge')
    place('lounge-sofa-south',aid('sofa'),3.7,-8.7,0,room='lounge')
    place('lounge-coffee-table','asset-'+PREFIX+'coffee-table',3.6,-6.4,color='#C99B39',room='lounge')
    place('lounge-display-cabinet',aid('sideboard'),1,-10.8,90,room='lounge')
    place('arcade',aid('arcade'),1.1,-14.2,90,room='lounge')
    place('table-football',aid('foosball-native'),11,-6,room='lounge')
    place('table-tennis',aid('folding-pingpong'),16,-11.3,room='lounge')
    place('lounge-waiting-bench',aid('unknown-seat'),8.8,-4.2,180,room='lounge')
    game=place('chess-table','asset-'+PREFIX+'chess-plinth',9,-10,color='#17191C',room='lounge')
    attach('chess-set','asset-gym-wellness-chess-set',game,'top',0,0,color='#C99B39')
    for i,(x,z,yaw) in enumerate([(7.9,-10,90),(10.1,-10,270),(9,-8.9,180),(9,-11.1,0)],1):
        place(f'chess-chair-{i}','asset-chair-black',x,z,yaw,color='#35393E',room='lounge')
    table=place('tabletop-game-plinth','asset-'+PREFIX+'chess-plinth',9,-15.3,color='#17191C',room='lounge')
    attach('tabletop-foosball','asset-gym-wellness-foosball',table,'top',0,0)
    for i,(x,yaw) in enumerate([(7.9,90),(10.1,270)],1):place(f'game-chair-{i}','asset-chair-black',x,-15.3,yaw,color='#35393E',room='lounge')
    # Eight seats around the measured conference table, all facing inward.
    place('conference-table','asset-breakroom-conference-table',26,-7,90,color='#35393E',room='conference')
    n=0
    for sign in [-1,1]:
        for z in [-8.15,-7,-5.85]:
            n+=1;place(f'conference-chair-{n}','asset-chair-black',26+sign*1.4,z,-sign*90,color='#17191C',room='conference')
    for z,yaw in [(-9.05,0),(-4.95,180)]:
        n+=1;place(f'conference-chair-{n}','asset-chair-black',26,z,yaw,color='#17191C',room='conference')
    screen=place('conference-screen','asset-breakroom-conference-screen',26,-10.84,0,y=1.3,color='#17191C',room='conference')
    wall=placed['meeting-cafe-divider']
    wall_box=catalog[wall['assetId']]['definition']['geometry']['aabb']
    screen_box=catalog[screen['assetId']]['definition']['geometry']['aabb']
    screen['transform']['position']['z']=wall['transform']['position']['z']+wall_box['maximum']['z']+.02-screen_box['minimum']['z']
    screen['snapRelationship']=dict(family='wall_attachment',supportPlacementId=wall['placementId'],
        supportAssetDefinitionRevision=wall['assetDefinitionRevision'],face='positive_z',localX=0,localY=1.3,normalGapMeters=.02)
    # Reuse the existing office furniture instead of deleting it.
    desk=move('Staff Desk',33,-8.5,90);move('Staff Chair',33,-7.35,180)
    move('Staff Storage',35.1,-9,270);move('Staff Drawers',35.1,-6.5,270)
    attach('work-monitor','asset-screen-21',desk,'worktop',.16,0,-90,color='#17191C')
    attach('work-keyboard','asset-keyboard',desk,'worktop',-.18,0,-90,color='#35393E')
    attach('work-mouse','asset-mouse',desk,'worktop',-.18,-.38,-90,color='#17191C')
    place('work-computer','asset-computer-case',32.1,-8.6,color='#17191C',room='work')
    place('work-guest-chair','asset-chair-black',31.7,-5.4,180,color='#35393E',room='work')
    # Small kitchenette reuses the already measured safe appliance worktop.
    kitchen=place('kitchen-assembly','asset-kitchen-assembly-appliance-worktop',24.6,-14.5,color='#45484B',room='kitchen')
    attach('coffee-pot','asset-breakroom-coffee-pot',kitchen,'island-appliance-worktop',.76,.83,-90,color='#17191C')
    attach('microwave','asset-breakroom-microwave',kitchen,'island-appliance-worktop',.55,1.4,-90,color='#92999F')
    place('fridge','asset-breakroom-refrigerator',27.2,-16.7,0,color='#92999F',room='kitchen')
    for i,x in enumerate((30.3,33.4),1):
        place(f'cafe-table-{i}','asset-5589t51-round-plastic-folding-table',x,-14.5,color='#C99B39',room='cafe')
        for j,(dx,dz,yaw) in enumerate([(-1.15,0,90),(1.15,0,270),(0,-1.15,0),(0,1.15,180)],1):
            place(f'cafe-chair-{i}-{j}','asset-chair-black',x+dx,-14.5+dz,yaw,color='#17191C',room='cafe')
    paths=[('entrance',[(6,-18),(6,-1.5)],1.5),
           ('work-corridor',[(6,-1.5),(33,-1.5)],1.5),
           ('gym-connection',[(21.1,-1.5),(21.1,.4),(20,.4),(20,7.5)],1.2),
           ('conference-door',[(26,-1.5),(26,-4)],1.2),
           ('work-door',[(33,-1.5),(33,-4.5)],1.2),
           ('cafe-access',[(6,-16.6),(20.6,-16.6),(20.6,-14.5),(22.65,-14.5)],1.2),
           ('recovery-access',[(58.5,10),(58.5,9.3),(57.3,8.2),(57.3,1.1)],1.2),
           ('washroom-access',[(50.8,21),(53,21),(53,18)],1.2),
           ('changing-access',[(50.8,23),(55.5,23),(55.5,25.1)],1.2)]
    details['paths']=paths
    # Navigation checks are retained separately; no decorative route paint is needed indoors.
    details['newIds']=[o['placement']['placementId'] for o in ops if o['op']=='place_asset']
    return ops,details


def audit(before,after,catalog,details):
    from shapely.geometry import box,LineString
    old={p['placementId']:p for p in before['placements']};new={p['placementId']:p for p in after['placements']}
    for pid,p in old.items():
        if pid in details['removed']:assert pid not in new
        elif pid not in details['moved']:assert new[pid]==p,('Unrelated placement modified',pid)
        else:
            a=deepcopy(p);b=deepcopy(new[pid]);a.pop('transform');b.pop('transform')
            assert a==b,('Move changed metadata',pid)
    assert before['routes']==after['routes']
    original_walls=deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    current_walls=deepcopy(after['extensions']['facilityPerimeterWalls']['settings'])
    current_walls['openings'].remove(dict(edge=0,startMeters=20.4,endMeters=21.8))
    assert original_walls==current_walls,'Existing wall finishes/openings changed'
    touched=[new[i] for i in details['newIds']+details['moved']]
    shapes={p['placementId']:footprint(p,catalog[p['assetId']]) for p in after['placements']}
    for p in touched:
        room=p['metadata'].get('room')
        if room:assert box(*ROOMS[room][1]).buffer(.001).covers(shapes[p['placementId']]),('Room boundary',p['placementId'])
    blocked=[]
    for key,points,width in details['paths']:
        area=LineString(points).buffer(width/2,cap_style=2,join_style=2)
        for p in after['placements']:
            if p['transform']['position']['y']>2:continue
            if area.intersection(shapes[p['placementId']]).area>=1e-6:blocked.append(('circulation',key,p['placementId']))
    for d in details['doors']:
        for p in touched:
            if p['transform']['position']['y']>2:continue
            if box(*d['bounds']).intersection(shapes[p['placementId']]).area>=1e-6:blocked.append(('door',d['name'],p['placementId']))
    # AABB overlap is conservative; support attachments and intentional fixture assemblies are explicit exceptions.
    overlaps=[]
    for index,p in enumerate(touched):
        for q in touched[index+1:]:
            if (p.get('snapRelationship') or q.get('snapRelationship')):continue
            py=p['transform']['position']['y'];qy=q['transform']['position']['y']
            ph=catalog[p['assetId']]['definition']['geometry']['aabb']['maximum']['y']
            qh=catalog[q['assetId']]['definition']['geometry']['aabb']['maximum']['y']
            if min(py+ph,qy+qh)<=max(py,qy)+.005:continue
            area=shapes[p['placementId']].intersection(shapes[q['placementId']]).area
            if area>1e-6:overlaps.append([p['placementId'],q['placementId'],area])
    write(OUT/'overlap-audit.json',overlaps)
    assert not overlaps and not blocked,dict(overlaps=overlaps,blocked=blocked)
    assert sum(p['placementId'].startswith(P+'recovery-chair-') for p in touched)==3
    assert sum(p['placementId'].startswith(P+'recovery-table-') for p in touched)==2
    assert sum(p['placementId'].startswith(P+'conference-chair-') for p in touched)==8
    assert all(p['transform']['scale']==1 for p in touched)
    return dict(capacities=details['capacities'],newPlacements=len(details['newIds']),
        relocatedPlacements=len(details['moved']),replacedSinks=len(details['removed']),
        originalWorkoutEquipmentAndArtworkUnchanged=True,checkedCirculationPaths=len(details['paths']),
        blockedDoors=0,unapprovedOverlaps=0,conceptScaleAssets=['massage-chair','arcade'],
        excludedFromLayout=['miniature piano','spare IGES table tennis','duplicate chess pieces','loose drawer insert'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['theme','stage','revise','publish-assets','save'])
    args=parser.parse_args()
    if args.phase=='theme':theme_assets();return
    OUT.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json');manifest=ROOT/PRIVATE_ASSET_MANIFEST;staged=OUT/'staged-project'
    if args.phase not in {'stage','revise'}:
        report=json.loads((OUT/'report.json').read_text())
        assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed during review'
        if args.phase=='publish-assets':
            baseline=OUT/'catalog-publication-base.json'
            if not baseline.exists():baseline=OUT/'catalog-before.json'
            assert report['status']=='validated' and manifest.read_bytes()==baseline.read_bytes()
            for rel in report['artifacts']:
                dest=ROOT/rel;payload=(staged/rel).read_bytes()
                if dest.exists():assert dest.read_bytes()==payload,'Published artifact changed: '+rel
                else:RevisionedAuthorityRepository._atomic_write(dest,payload)
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            assert report['status']=='assets-published'
            raw=(OUT/'candidate.json').read_bytes();native=json.loads((OUT/'native-check.json').read_text())
            assert native['status']=='preview-verified' and native['candidateHash']==hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for rel,digest in report['assetHashes'].items():assert hashlib.sha256((ROOT/rel).read_bytes()).hexdigest()==digest
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,json.loads(raw),report['baseRevision'])
            finally:host.close()
            write(OUT/'saved.json',receipt['layout']);report.update(status='saved',savedRevision=receipt['revision'])
            hashes=saved_hashes();assert all(hashes[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged']=True
        write(OUT/'report.json',report);print(report['status']);return
    raw=target.read_bytes();before=json.loads(raw);catalog_raw=manifest.read_bytes()
    if args.phase=='revise':
        report=json.loads((OUT/'report.json').read_text())
        assert report['status']=='assets-published','Only an unpublished layout can be revised'
        assert raw==(OUT/'before.json').read_bytes(),'Saved gym changed during review'
        assert catalog_raw==(staged/PRIVATE_ASSET_MANIFEST).read_bytes(),'Published catalog changed'
        archive=OUT/('review-'+hashlib.sha256((OUT/'candidate.json').read_bytes()).hexdigest()[:16])
        archive.mkdir(exist_ok=True)
        for path in OUT.iterdir():
            if path.is_file() and path.suffix in {'.json','.png'} and not (archive/path.name).exists():
                copy2(path,archive/path.name)
        (OUT/'catalog-publication-base.json').write_bytes(catalog_raw)
        catalog_raw=(OUT/'catalog-before.json').read_bytes()
        write(OUT/'native-check.json',dict(status='needs-review'))
    for name,data in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        path=OUT/name
        if path.exists():assert path.read_bytes()==data,'Base changed'
        else:path.write_bytes(data)
    library=json.loads(catalog_raw);artifacts,imported=prepare_assets(library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops,details=operations(before,catalog);write(OUT/'operations.json',ops);write(OUT/'details.json',details)
        candidate=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        write(OUT/'candidate-draft.json',candidate)
        checks=audit(before,candidate,catalog,details)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        write(OUT/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
    finally:host.close()
    write(OUT/'candidate.json',receipt['layout'])
    asset_hashes={rel:hashlib.sha256(((staged if rel in artifacts else ROOT)/rel).read_bytes()).hexdigest() for rel in artifacts+imported}
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),layoutHashes=saved_hashes(),
        artifacts=artifacts,assetHashes=asset_hashes,checks=checks,limitations=[
            'Concept furnishing layout, not building, plumbing, accessibility or safety certification.',
            'STL furniture units are provisional; massage chair and arcade have explicit concept-size display copies.',
            'The small piano source remains in the library but is not furnished until scale and configuration are confirmed.',
            'Wash bays show clear door openings; final doors, ventilation and plumbing remain design work.']))
    profile=json.loads((ROOT/'.runtime/private-gym-truck-ring-20261008/profile.json').read_text())
    profile.update(profileId='private-gym-wellness',origin='http://127.0.0.1:8558',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):return dict(name=name,position=dict(zip(('x','y','z'),p)),target=dict(zip(('x','y','z'),t)),thresholds=dict(detail=1000))
    overview=shot('01-wellness-overview',(68,86,-64),(30,0,15))
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],minimumAssetMeshes=1,
        requiredAssets=[aid(k) for k in ['sofa','locker','massage-chair','massage-table','vanity','folding-pingpong']],
        shots=[overview,shot('02-annex-top',(18,52,-10),(18,0,-9)),shot('03-social-lounge',(20,4,-4),(6,1,-10)),
               shot('04-conference',(23,3,-3.7),(26,1,-8)),shot('05-workspace',(31,2.6,-4),(33,1,-8.5)),
               shot('06-cafe',(34,3,-12),(24.5,1,-15)),shot('07-recovery',(57.4,4,9),(57,0,3.5)),
               shot('08-private-washrooms',(55.5,8,20.5),(55.5,0,14)),shot('09-lockers',(55.5,2.5,23.5),(55.5,1,28.5)),
               shot('10-lounge-branding',(5,2.5,-13),(2.6,1.6,-17.8)),
               shot('11-double-vanity',(54,2.3,18.5),(55.8,1,21.5))],
        finalShot=dict(overview,name='12-saved-wellness-campus')))
    print(json.dumps(checks))


if __name__=='__main__':main()
