"""Stage, verify, and revision-bound save the requested Private Gym sports annex."""
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

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
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

OUT = ROOT/'.runtime/private-gym-sports-20261007'
SOURCE = Path('C:/Users/might/Downloads/Video/boxing room and basketball court')
PREFIX = 'private-gym-sports-'
SPORTS = ['basketball-hoop', 'boxing-ring', 'boxing-bag']
COURT = dict(centerX=71.5, endlineZ=34, halfZ=20, width=15, length=14, rimZ=32.425)


def court_markings():
    """FIBA-based half court, represented by editable existing line primitives."""
    result = []
    cx, end, half, rim = (COURT[k] for k in ('centerX','endlineZ','halfZ','rimZ'))
    def line(key, a, b, width=.05):
        dx, dz = b[0]-a[0], b[1]-a[1]
        result.append(dict(key=key, x=(a[0]+b[0])/2, z=(a[1]+b[1])/2,
                           width=math.hypot(dx,dz), depth=width,
                           rotation=-math.degrees(math.atan2(dz,dx))))
    def arc(key, center, radius, first, last, count, dashed=False):
        for i in range(count):
            if dashed and i%4 >= 2: continue
            a, b = [first+(last-first)*j/count for j in (i,i+1)]
            line(key+'-'+str(i), (center[0]+radius*math.cos(a),center[1]-radius*math.sin(a)),
                 (center[0]+radius*math.cos(b),center[1]-radius*math.sin(b)))
    for key,a,b in [
        ('baseline',(64-.025,end+.025),(79+.025,end+.025)),
        ('halfway',(64-.025,half-.025),(79+.025,half-.025)),
        ('sideline-left',(63.975,half),(63.975,end)),
        ('sideline-right',(79.025,half),(79.025,end)),
        ('key-left',(cx-2.425,end),(cx-2.425,28.225)),
        ('key-right',(cx+2.425,end),(cx+2.425,28.225)),
        ('free-throw',(cx-2.45,28.225),(cx+2.45,28.225)),
    ]: line(key,a,b)
    radius = 6.725
    angle = math.acos(6.575/radius)
    join_z = rim-radius*math.sin(angle)
    line('three-left',(cx-6.575,end),(cx-6.575,join_z))
    line('three-right',(cx+6.575,end),(cx+6.575,join_z))
    arc('three-point',(cx,rim),radius,angle,math.pi-angle,96)
    arc('free-throw-front',(cx,28.225),1.775,0,math.pi,48)
    arc('free-throw-dashed',(cx,28.225),1.775,math.pi,2*math.pi,48,True)
    arc('center-circle',(cx,half),1.775,math.pi,2*math.pi,48)
    arc('restricted-area',(cx,rim),1.225,0,math.pi,40)
    for side in (-1,1):
        line('restricted-return-'+str(side),(cx+side*1.225,rim),(cx+side*1.225,32.8))
    return result


def prepare_assets(library):
    staged = OUT/'staged-project'
    artifacts = []
    for key in SPORTS:
        folder = ROOT/'generated/industrial_assets/local_library'/('gym-sports-'+key)
        entry = json.loads((folder/'catalog-entry.json').read_text())
        assert not any(a['assetId']==entry['assetId'] for a in library['assets'])
        library['assets'].append(entry)
    hoop=next(a for a in library['assets'] if a['assetId']=='asset-gym-sports-basketball-hoop')
    hoop_rear=COURT['rimZ']+.3861157+hoop['sourceToCanonical'][14]+hoop['dimensions']['depth']/2
    support_depth=36-.01-hoop_rear
    specs = [
        ('court-back',19.6,.3,5.5,'basketball 1.png',-1),
        ('court-left',17.98,.3,5.5,'basketball 2.png',1),
        ('court-right',17.98,.3,5.5,'basketball 3.png',-1),
        ('boxing-south',21.79,.3,4.2,'Fighting Spirit in the Ring.png',1),
        ('boxing-north',15.79,.3,4.2,'ChatGPT Image Oct 7, 2026, 07_53_31 PM.png',-1),
        ('boxing-north-return',4,.3,4.2,None,1),
        ('boxing-east',15.36,.3,4.2,None,1),
        ('hoop-support',.8,support_depth,1.1,None,1),
    ]
    for key,w,d,h,art,face in specs:
        aid = 'asset-'+PREFIX+key
        assert not any(a['assetId']==aid for a in library['assets'])
        dimensions = dict(width=w,depth=d,height=h)
        folder = Path('generated/industrial_assets/private_gym/sports')/key
        artifact = (folder/'model.glb').as_posix()
        source = dict(kind='authored-primitive', generator=Path(__file__).name)
        if art:
            png = (SOURCE/art).read_bytes()
            payload = wall_glb(png,dimensions,fit='contain',face=face,name=key+' original artwork')
            texture = (folder/'artwork.png').as_posix()
            target = staged/texture;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(png)
            artifacts.append(texture)
            source.update(originalFile=art,sha256=hashlib.sha256(png).hexdigest(),fit='contain',imageModified=False)
        elif key=='hoop-support':
            # Open cantilever frame, not a solid beam blocking sight of the mural.
            import trimesh
            scene = trimesh.Scene()
            for x,y,z,ww,hh,dd in [(-.35,.15,0,.1,.1,d),(.35,.15,0,.1,.1,d),
                                    (-.35,.95,0,.1,.1,d),(.35,.95,0,.1,.1,d),
                                    (0,.55,d/2-.05,.8,1.1,.1),(0,.55,-d/2+.05,.8,1.1,.1)]:
                mesh=trimesh.creation.box(extents=[ww,hh,dd]);mesh.apply_translation([x,y,z]);scene.add_geometry(mesh)
            payload=scene.export(file_type='glb')
            source['limitation']='Concept support frame; anchors, loads and structural design unverified.'
        else: payload = box_glb(w,d,h)
        target = staged/artifact;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(payload)
        artifacts.append(artifact)
        library['assets'].append(dict(assetId=aid, displayName='Private Gym '+key.replace('-',' ').title(),
            category='Building Structures',dimensions=dimensions,artifact=artifact,sourceToCanonical=IDENTITY,
            tags=['gym','sports','wall' if key!='hoop-support' else 'mounting-bracket'],source=source,
            description='Concept sports annex architecture; installation and structural ratings unverified.'))
    library['summary']['total']=len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    return artifacts


def operations(before,catalog):
    walls = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    walls.update(boundarySource='polygon',boundary=[dict(x=x,z=z) for x,z in [(0,0),(60,0),(60,30),(0,30)]])
    ops = [dict(op='set_perimeter_walls',wallSettings=walls),
           dict(op='set_plan_settings',planSettings=dict(widthMeters=82,depthMeters=36.5,gridSpacingMeters=.5,majorGridSpacingMeters=5))]
    surfaces=[]
    for key,bounds,color in [('original',(0,0,60,30),'#d8e0df'),('annex',(60,0,82,16),'#3e474e'),
                             ('court-apron',(60,16,82,36.5),'#526f77')]:
        x0,z0,x1,z1=bounds
        surfaces.append(dict(surfaceId=PREFIX+key,minX=x0,maxX=x1,minZ=z0,maxZ=z1,
            startElevation=0,endElevation=0,slopeAxis='x',color=color))
    ops.append(dict(op='set_ground',ground=dict(schemaVersion=1,surfaces=surfaces)))
    def zone(key,label,bounds,color):
        x0,z0,x1,z1=bounds
        ops.append(dict(op='add_zone',zone=dict(zoneId='zn-'+PREFIX+key,label=label,zoneType='workcell',
            boundary=[dict(x=x0,z=z0),dict(x=x1,z=z0),dict(x=x1,z=z1),dict(x=x0,z=z1)],
            floorElevation=0,anchors=[],evidence=[],extensions=dict(style=dict(fillColor=color)))))
    zone('boxing','Boxing + Combat Training',(60,0,82,16),'#786577')
    zone('outdoor','Outdoor Basketball + Run-Off',(60,16,82,36.5),'#639293')
    placed={}
    def place(key,asset,x,z,yaw=0,y=0,color=None,role='architecture'):
        q=math.radians(yaw)/2
        p=dict(placementId='pl-'+PREFIX+key,assetId=asset,assetDefinitionRevision=catalog[asset]['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1),
            positionMode='manual',snapRelationship=None,metadata=dict(instanceLabel=key.replace('-',' ').title(),gymRole=role,inputMethod='independent-authoring'))
        if color:p['appearance']=dict(color=color)
        ops.append(dict(op='place_asset',placement=p))
        placed[key]=p
        return p
    def attach(key,asset,parent_key,face,local_x,local_y,color=None):
        parent=placed[parent_key]
        a=catalog[parent['assetId']]['definition']['geometry']['aabb']
        b=catalog[asset]['definition']['geometry']['aabb']
        positive=face=='positive_z'
        local_z=(a['maximum']['z']+.005-b['minimum']['z'] if positive else a['minimum']['z']-.005+b['minimum']['z'])
        q=parent['transform']['quaternion'];angle=2*math.atan2(q['y'],q['w'])
        pp=parent['transform']['position']
        p=place(key,asset,pp['x']+math.cos(angle)*local_x+math.sin(angle)*local_z,
            pp['z']-math.sin(angle)*local_x+math.cos(angle)*local_z,
            math.degrees(angle)+(0 if positive else 180),y=pp['y']+local_y,color=color,role='equipment')
        p['snapRelationship']=dict(family='wall_attachment',supportPlacementId=parent['placementId'],
            supportAssetDefinitionRevision=parent['assetDefinitionRevision'],face=face,localX=local_x,localY=local_y,normalGapMeters=.005)
        return p
    for key,x,z,yaw,color in [
        ('court-back',71.5,36.15,0,'#293a43'),('court-left',61.85,27,90,'#293a43'),
        ('court-right',81.15,27,90,'#293a43'),('boxing-south',71,.15,0,'#deddd7'),
        ('boxing-north',68,15.85,0,'#deddd7'),('boxing-north-return',80,15.85,0,'#deddd7'),
        ('boxing-east',81.85,8,90,'#deddd7')]:
        place(key,'asset-'+PREFIX+key,x,z,yaw,color=color)
    place('boxing-ring','asset-gym-sports-boxing-ring',69.2,8,role='equipment')
    attach('boxing-bag','asset-gym-sports-boxing-bag','boxing-east','negative_z',3,.25)
    hoop=catalog['asset-gym-sports-basketball-hoop']
    import numpy as np
    matrix=np.asarray(hoop['definition']['coordinateFrame']['sourceToCanonical']).reshape((4,4),order='F')
    rim=matrix@np.array([0,-.19350451,.3861157,1])
    attach('hoop-support','asset-'+PREFIX+'hoop-support','court-back','negative_z',0,2.7,color='#394952')
    p=attach('basketball-hoop','asset-gym-sports-basketball-hoop','hoop-support','positive_z',0,3.05-rim[1]-2.7)
    assert abs(p['transform']['position']['z']-rim[2]-COURT['rimZ'])<1e-7
    def mark(key,x,z,w,d,color,y=.014,rotation=0,text=''):
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-'+PREFIX+key,label=key.replace('-',' ').title(),
            markingType='floor_text' if text else 'solid_line',semanticRole='decorative',positionMode='manual',
            transform=dict(position=dict(x=x,y=y,z=z),rotationDegrees=rotation),width=w,depth=d,
            fillColor=color,strokeColor=color,opacity=1,text=text,evidence=[],metadata=dict(authoredIn=PREFIX))))
    mark('court-surface',71.5,27,15,14,'#2c656d',y=.004)
    mark('painted-key',71.5,31.1,4.9,5.8,'#bd624c',y=.008)
    mark('boxing-bag-training-mat',78.8,5,5,6,'#354d60',y=.005)
    for item in court_markings():
        mark(item['key'],item['x'],item['z'],item['width'],item['depth'],'#f3f0e7',rotation=item['rotation'])
    mark('boxing-label',70,1.6,7,.7,'#e7e6dc',text='BOXING + COMBAT')
    mark('court-label',71.5,18.8,7,.6,'#e7e6dc',text='PRIVATE GYM | BASKETBALL')
    paths=[('boxing-entry',[(59,11),(62.5,11),(62.5,14.4),(77,14.4),(77,17)],1.2),
           ('court-entry',[(77,17),(71.5,17),(71.5,19)],1.2),
           ('bag-access',[(77,14.4),(76,11),(77.5,8.8)],1.2)]
    for key,points,width in paths:
        ops.append(dict(op='add_aisle',routeId='rt-'+PREFIX+key,aisle=dict(label=key.replace('-',' ').title(),
            centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,aisleKind='pedestrian',direction='two_way',
            color='#899ca2',clearanceEvidenceStatus='unverified')))
    return ops,paths


def audit(before,after,catalog,paths):
    from shapely.geometry import LineString,box
    for field,key in [('placements','placementId'),('zones','zoneId'),('routes','routeId'),('floorMarkings','markingId')]:
        current={p[key]:p for p in after[field]}
        assert all(current[p[key]]==p for p in before[field]), 'Existing '+field+' changed'
    added=[p for p in after['placements'] if p['placementId'] not in {x['placementId'] for x in before['placements']}]
    shapes={p['placementId']:footprint(p,catalog[p['assetId']]) for p in added}
    for key,points,width in paths:
        route=LineString(points).buffer(width/2,cap_style=2,join_style=2)
        for p in added:
            assert route.intersection(shapes[p['placementId']]).area<1e-6,(key,p['placementId'])
    ring=shapes['pl-'+PREFIX+'boxing-ring']
    assert box(60.3,.3,81.7,15.7).covers(ring.buffer(1.5,join_style=2))
    court=box(64,20,79,34)
    for p in added:
        if p['metadata']['gymRole']=='architecture' and 'hoop-support' not in p['placementId']:
            assert court.distance(shapes[p['placementId']])>=1.999,(p['placementId'],'court runoff')
    assert len(added)==11
    return dict(unchangedPlacements=len(before['placements']),addedPlacements=len(added),
                originalGeometryUnchanged=True,courtPlayingArea=[15,14],minimumCourtRunoff=2,
                ringClearPerimeterAtLeast=1.5,blockedAuthoredWalkways=0)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish-assets','save'])
    args=parser.parse_args()
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST;staged=OUT/'staged-project'
    if args.phase!='stage':
        report=json.loads((OUT/'report.json').read_text())
        reconciled=None
        if args.phase=='save' and (OUT/'saved.json').exists():
            saved=json.loads((OUT/'saved.json').read_text())
            assert json.loads(target.read_bytes())==saved,'Saved gym changed after publication'
            expected=json.loads((OUT/'candidate.json').read_text())
            expected['updatedAt']=saved['updatedAt']
            assert expected==saved,'Saved receipt differs from the reviewed candidate'
            reconciled=dict(layout=saved,revision=layout_revision(saved))
        else:
            assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed during review'
        if args.phase=='publish-assets':
            assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes()
            for artifact in report['artifacts']:
                dest=ROOT/artifact;assert not dest.exists()
                dest.parent.mkdir(parents=True,exist_ok=True)
                RevisionedAuthorityRepository._atomic_write(dest,(staged/artifact).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            native=json.loads((OUT/'native-check.json').read_text())
            assert native['status']=='preview-verified'
            raw=(OUT/'candidate.json').read_bytes()
            assert native['candidateHash']==hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            if reconciled:receipt=reconciled
            else:
                host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
                try:receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,json.loads(raw),report['baseRevision'])
                finally:host.close()
            write(OUT/'saved.json',receipt['layout'])
            report.update(status='saved',savedRevision=receipt['revision'])
            after=saved_hashes()
            assert all(after[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report['otherLayoutsUnchanged']=True
        write(OUT/'report.json',report);print(json.dumps(dict(status=report['status'])));return
    OUT.mkdir(parents=True,exist_ok=True)
    raw=target.read_bytes();before=json.loads(raw);catalog_bytes=manifest.read_bytes()
    for name,data in [('before.json',raw),('catalog-before.json',catalog_bytes)]:
        snapshot=OUT/name
        if snapshot.exists():assert snapshot.read_bytes()==data,'Base changed'
        else:snapshot.write_bytes(data)
    library=json.loads(catalog_bytes);artifacts=prepare_assets(library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
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
    report=dict(status='validated',baseRevision=layout_revision(before),layoutHashes=saved_hashes(),artifacts=artifacts,checks=checks,
        limitations=['Concept gym extension, not structural, fire, accessibility or sports-facility certification.',
                     'Supplied recreational backboard retained at actual CAD scale, with rim top at 3.05 m.',
                     'Bag suspension, hoop cantilever, anchors and wall structure require engineering review.'])
    write(OUT/'report.json',report)
    profile=json.loads((ROOT/'.runtime/private-gym-eagle-full-wall-20261007/profile.json').read_text())
    profile.update(profileId='private-gym-sports-review',origin='http://127.0.0.1:8541',dataRoot=str(OUT),backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    shots=[dict(name='01-extension-overview',position=dict(x=96,y=44,z=6),target=dict(x=64,y=0,z=17),thresholds=dict(detail=1000)),
           dict(name='02-court',position=dict(x=71.5,y=5,z=17.8),target=dict(x=71.5,y=2.5,z=34),thresholds=dict(detail=1000)),
           dict(name='03-boxing',position=dict(x=78.7,y=3.3,z=13.2),target=dict(x=69.5,y=1.5,z=5),thresholds=dict(detail=1000)),
           dict(name='04-bag',position=dict(x=76.5,y=2,z=8.5),target=dict(x=80.5,y=1.5,z=5),thresholds=dict(detail=1000)),
           dict(name='05-wrestlers',position=dict(x=64,y=2.5,z=8),target=dict(x=68,y=2,z=15.7),thresholds=dict(detail=1000))]
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],requiredAssets=['asset-'+PREFIX+k for k in ['court-back','court-left','court-right','boxing-north','boxing-south']],
        shots=shots,finalShot=dict(name='saved-sports-extension',position=dict(x=90,y=33,z=10),target=dict(x=67,y=0,z=18),thresholds=dict(detail=1000))))
    print(json.dumps(dict(status=report['status'],checks=checks)))


if __name__=='__main__':main()
