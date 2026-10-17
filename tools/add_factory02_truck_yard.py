"""Stage, verify and publish a revision-bound mixed-fleet yard for Factory 02."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shapely.geometry import box
from ai_inspector.facility_layout.authority_repository import _native_fs_path, RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb
from tools.add_factory02_dispatch_office import LAYOUT_ID, SITE, STORE
from tools.add_factory02_parking_office import boundary, hashes, write_json, verify_native_candidate
from tools.expand_factory02_lunchroom import rectangle_tiles
from tools.audit_independent_factory_layer2 import footprint
from tools.derive_straight_truck import derive, ASSET as BIG, SOURCE as BIG_SOURCE

BASE = '5bd2c22d4f59e61c7e7d5cec433fa89fe011def2573a3c483306cfd9307f16cb'
YARD_Y = -1.35
SMALL = 'asset-truck-20ft-container'
BAYS = [('S1',20,BIG),('S2',44,BIG),('S3',68,SMALL),
        ('R1',132,BIG),('R2',156,BIG),('R3',180,SMALL)]
REMOVED = {'pl-independent-wall-west-south','pl-independent-wall-west-north'}
FLOORS = {BIG:1.3000000518222807, SMALL:1.374600529670716}


def surface(sid, b, start, end=None, color='#536069'):
    x0,z0,x1,z1=b
    return dict(surfaceId=sid,minX=x0,maxX=x1,minZ=z0,maxZ=z1,startElevation=start,
        endElevation=start if end is None else end,slopeAxis='x',color=color)


def ground(before):
    plan=before['extensions']['facilityPlan']
    ramp=surface('yard-central-ramp',(-24,94,0,102),YARD_Y,0,'#919da3')
    bridges=[surface('dock-bridge-'+key,(-1,z-1.15,0,z+1.15),YARD_Y+FLOORS[aid],0,'#abb4ba')
             for key,z,aid in BAYS]
    cuts=[box(s['minX'],s['minZ'],s['maxX'],s['maxZ']) for s in [ramp]+bridges]
    tiles=rectangle_tiles((-82,0,0,plan['depthMeters']),cuts)
    return dict(schemaVersion=1,surfaces=[surface('factory-main',(0,0,plan['widthMeters'],plan['depthMeters']),0,color='#c8d3d9')]
        +[surface(f'yard-{i:03}',b,YARD_Y) for i,b in enumerate(tiles)]+[ramp]+bridges)


def panels():
    result=[]
    for a,b in [(.27,91.01),(105.99,199.77)]:
        cursor=a
        for key,z,_ in BAYS:
            if not a<z<b:continue
            result.append((f'west-{key}-before',(0,cursor,.25,z-2.25),6))
            cursor=z+2.25
        result.append((f'west-{int(a)}-end',(0,cursor,.25,b),6))
    return result


def specs():
    result=[derive()[1]]
    for key,b,h in panels()+[('bumper',(-.175,-.20,.175,.20),1.2)]:
        result.append(dict(assetId='asset-factory02-perimeter-yard-'+key,
            displayName='Dock '+key,category='Building Structures',
            dimensions=dict(width=b[2]-b[0],depth=b[3]-b[1],height=h),
            artifact=f'generated/industrial_assets/factory02_truck_yard/{key}/model.glb',
            description='Authored concept dock component; no structural or traffic qualification.',
            tags=['perimeter','wall','dock'] if key!='bumper' else ['dock','bumper'],
            source=dict(kind='authored-primitive',generator=Path(__file__).name),
            sourceToCanonical=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]))
    return result


def truck_pose(aid, z):
    # Measured rear of each container in its canonical metre frame.
    if aid==BIG:
        rear=(0,derive()[2])
        yaw=-math.pi/2
    else:
        rear=(0,-4.338132739067078)
        yaw=-math.pi/2
    rx=math.cos(yaw)*rear[0]+math.sin(yaw)*rear[1]
    rz=-math.sin(yaw)*rear[0]+math.cos(yaw)*rear[1]
    # Keep a millimetre of contact clearance after canonical coordinate rounding.
    return -1.001-rx,z-rz,yaw


def operations(before,catalog):
    assert before['layoutId']==LAYOUT_ID and layout_revision(before)==BASE,'Saved Factory 02 changed'
    ops=[dict(op='set_ground',ground=ground(before))]
    for pid in sorted(REMOVED):ops.append(dict(op='delete_placement',placementId=pid))
    def zone(key,label,b):
        ops.append(dict(op='add_zone',zone=dict(zoneId='zn-yard-'+key,label=label,zoneType='workcell',
            boundary=boundary(b),floorElevation=YARD_Y,anchors=[],evidence=[],
            extensions=dict(style=dict(fillColor='#a6b6bc')))))
    zone('all','Truck Yard - Lower Level',(-82,0,0,200.04024))
    zone('shipping','Shipping Docks S1-S3',(-23,6,0,84))
    zone('receiving','Receiving Docks R1-R3',(-23,116,0,194))
    zone('waiting','Truck Holding',(-81,20,-62,181))
    zone('wall-strip','Dock Wall + Door Openings',(0,0,.25,200.04024))
    def place(key,aid,x,y,z,yaw=0):
        a=catalog[aid]
        ops.append(dict(op='place_asset',placement=dict(placementId='pl-yard-'+key,assetId=aid,
            assetDefinitionRevision=a['assetDefinitionRevision'],positionMode='locked' if 'perimeter' in aid else 'manual',
            snapRelationship=None,metadata=dict(instanceLabel=key,inputMethod='independent-authoring'),
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(yaw/2),z=0,w=math.cos(yaw/2)),scale=1))))
    def paint(key,kind,b,text='',color='#f4da62',y=YARD_Y,rotation=0):
        x0,z0,x1,z1=b
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-yard-'+key,
            markingType=kind,label=key,semanticRole='decorative',
            transform=dict(position=dict(x=(x0+x1)/2,y=y,z=(z0+z1)/2),rotationDegrees=rotation),
            width=x1-x0,depth=z1-z0,fillColor=color,strokeColor=color,opacity=1,text=text,
            positionMode='manual',metadata=dict(authoredIn='truck_yard'),evidence=[])))
    for key,b,h in panels():
        place(key,'asset-factory02-perimeter-yard-'+key,(b[0]+b[2])/2,0,(b[1]+b[3])/2)
    for key,z,aid in BAYS:
        x,pz,yaw=truck_pose(aid,z)
        place('truck-'+key,aid,x,YARD_Y,pz,yaw)
        paint('bay-'+key,'parking_box',(-22,z-5,-1.05,z+5),key)
        paint('bay-label-'+key,'floor_text',(-24,z-2,-22.5,z+2),key,rotation=90)
        for side in [-1,1]:place(f'bumper-{key}-{side}','asset-factory02-perimeter-yard-bumper',-.3,YARD_Y,z+side*1.8)
        # Door-to-department connection stays in the existing clear west-side strip.
        paint('inside-'+key,'parking_box',(.35,z-2.1,5.7,z+2.1),'DOCK '+key,color='#f4da62',y=0)
    for i,(z,aid) in enumerate([(40,BIG),(82,BIG),(124,SMALL),(163,SMALL)],1):
        place('waiting-'+str(i),aid,-72,YARD_Y,z)
        paint('waiting-'+str(i),'parking_box',(-78,z-10,-66,z+10),'WAIT '+str(i))
    # One-way circulation is authored floor communication, not a steering simulation.
    for z in (12,40,70,112,145,181):
        paint('entry-arrow-'+str(z),'direction_arrow',(-57.5,z-2.5,-54.5,z+2.5),rotation=0)
        paint('exit-arrow-'+str(z),'direction_arrow',(-39.5,z-2.5,-36.5,z+2.5),rotation=180)
    for x in (-60,-52,-42,-34):paint('lane-'+str(x),'solid_line',(x,4,x+.15,192),color='#e8e9db')
    paint('north-turn','direction_arrow',(-50,192,-44,195),rotation=90)
    paint('entry','floor_text',(-60,1,-52,3),'IN')
    paint('exit','floor_text',(-42,1,-34,3),'OUT')
    paint('receiving','floor_text',(-48,197,-4,199),'RECEIVING')
    paint('shipping','floor_text',(-32,1,-4,3),'SHIPPING')
    return ops


def audit(before,after,catalog):
    old={p['placementId']:p for p in before['placements'] if p['placementId'] not in REMOVED}
    assert {p['placementId']:p for p in after['placements'] if p['placementId'] in old}==old
    for field in ['zones','routes','floorMarkings']:
        for item in before[field]:assert item in after[field],field
    for key,value in before['extensions'].items():assert after['extensions'][key]==value
    for key in set(before)-{'placements','zones','routes','floorMarkings','extensions','updatedAt'}:assert after[key]==before[key]
    shapes={p['placementId']:footprint(p,catalog[p['assetId']]) for p in after['placements']}
    new=[p for p in after['placements'] if p['placementId'].startswith('pl-yard-')]
    for p in new:
        for q in after['placements']:
            if p['placementId']!=q['placementId']:
                assert shapes[p['placementId']].intersection(shapes[q['placementId']]).area<1e-7,(p['placementId'],q['placementId'])
    ramp=box(-24,94,6,102)
    assert all(not shapes[p['placementId']].intersects(ramp) for p in new)
    assert sum(p['placementId'].startswith('pl-yard-truck-') for p in new)==6
    assert sum(p['placementId'].startswith('pl-yard-waiting-') for p in new)==4
    for key,z,aid in BAYS:
        assert not any(shapes[p['placementId']].intersects(box(.01,z-2,.24,z+2)) for p in after['placements'])
    return dict(loadingBays=6,waitingSpaces=4,trucks=10,unchangedExistingPlacements=len(old),
        movementProgramsPreserved=len(before['extensions']['facilityNavigation']['movementPrograms']),
        yardElevationMeters=YARD_Y,centralRampLengthMeters=24,centralRampRiseMeters=1.35,
        dockHeightsAboveYardMeters=FLOORS,originalTruckAssetsUnmodified=True,
        qualification='Geometric concept only; no turning-dynamics, dock-equipment rating, drainage, structural or safety approval.')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--publish-assets',action='store_true')
    parser.add_argument('--publish-layout',action='store_true')
    parser.add_argument('--native-report',type=Path)
    args=parser.parse_args();out=args.output.resolve()
    directory=STORE/'layouts/local/site-local/layouts';target=directory/(LAYOUT_ID+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST;staged=out/'staged-project'
    if args.publish_assets or args.publish_layout:
        report=json.loads((out/'report.json').read_text())
        assert target.read_bytes()==(out/'before.json').read_bytes(),'Saved layout changed'
        assert hashes(directory)==report['layoutHashes'],'Saved layouts changed'
        payload=(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
        if args.publish_assets:
            assert report['status']=='validated' and manifest.read_bytes()==(out/'catalog-before.json').read_bytes()
            for spec in specs():
                dest=ROOT/spec['artifact'];assert not dest.exists()
                dest.parent.mkdir(parents=True,exist_ok=True)
                RevisionedAuthorityRepository._atomic_write(dest,(staged/spec['artifact']).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,payload);report['status']='assets-published'
        else:
            assert report['status']=='assets-published' and args.native_report
            assert manifest.read_bytes()==payload
            candidate=json.loads((out/'candidate.json').read_text())
            assert layout_revision(candidate)==report['candidateRevision']
            verify_native_candidate(json.loads(args.native_report.read_text()),candidate,
                (out/'validation-store/layouts/local/site-local/layouts'/target.name).read_bytes())
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:saved=host.service.save_layout(host.principal(),SITE,LAYOUT_ID,candidate,BASE)
            finally:host.close()
            normalized=deepcopy(saved['layout']);normalized['updatedAt']=candidate['updatedAt'];assert normalized==candidate
            assert {k:v for k,v in hashes(directory).items() if k!=target.name}=={k:v for k,v in report['layoutHashes'].items() if k!=target.name}
            write_json(out/'saved.json',saved['layout'])
            report.update(status='saved',savedRevision=saved['revision'],nativeEvidencePath=str(args.native_report.resolve()))
        write_json(out/'report.json',report);print(json.dumps(dict(status=report['status'])));return
    before_bytes=target.read_bytes();before=json.loads(before_bytes);assert layout_revision(before)==BASE
    out.mkdir(parents=True,exist_ok=False);(out/'before.json').write_bytes(before_bytes)
    (out/'catalog-before.json').write_bytes(manifest.read_bytes())
    library=json.loads(manifest.read_text())
    assert not any(a['assetId'] in {s['assetId'] for s in specs()} for a in library['assets'])
    measurements=json.loads((ROOT/'.runtime/truck-dock-measurements/measurements.json').read_text())
    measured={m['assetId']:m for m in measurements['measurements']}
    for aid in (BIG_SOURCE,SMALL):
        spec=next(s for s in library['assets'] if s['assetId']==aid)
        assert hashlib.sha256((ROOT/spec['artifact']).read_bytes()).hexdigest()==measured[aid]['artifactSha256']
        assert abs(measured[aid]['heightAboveGroundMeters']-FLOORS[BIG if aid==BIG_SOURCE else aid])<1e-6
    write_json(out/'cargo-floor-evidence.json',measurements)
    library['assets'].extend(specs());library['summary']['total']=len(library['assets'])
    write_json(staged/PRIVATE_ASSET_MANIFEST,library)
    for spec in specs():
        d=spec['dimensions'];dest=staged/spec['artifact'];dest.parent.mkdir(parents=True,exist_ok=True)
        if spec['assetId']==BIG:
            dest.write_bytes(derive()[0]);continue
        dest.write_bytes(build_aabb_proxy_glb(dict(minimum=dict(x=-d['width']/2,y=0,z=-d['depth']/2),
            maximum=dict(x=d['width']/2,y=d['height'],z=d['depth']/2))))
    stage=out/'validation-store'
    copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'))
    copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'))
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops=operations(before,catalog)
        after=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks=audit(before,after,catalog);principal=host.principal()
        dependencies=host.service.validate_dependencies(principal,SITE,after).to_dict()
        spatial=host.service._diagnose_spatial(principal,SITE,after);routing=host.service._diagnose_routing(principal,SITE,after)
        write_json(out/'validation.json',dict(dependencies=dependencies,spatial=spatial,routing=routing))
        host.service._require_spatially_valid(spatial);host.service._require_routing_valid(routing)
        saved=host.service.save_layout(principal,SITE,LAYOUT_ID,after,BASE)
        write_json(out/'candidate.json',saved['layout']);write_json(out/'operations.json',ops)
        report=dict(status='validated',baseRevision=BASE,candidateRevision=saved['revision'],**checks,
            totalPlacements=len(after['placements']),layoutHashes=hashes(directory),spatialMetrics=spatial['metrics'])
        write_json(out/'report.json',report);print(json.dumps(report))
    finally:host.close()


if __name__=='__main__':main()
