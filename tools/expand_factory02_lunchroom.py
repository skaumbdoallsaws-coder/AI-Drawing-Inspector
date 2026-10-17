"""Relocate and expand Factory 02's cafeteria through revision-bound layout APIs."""
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
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path, RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb
from tools.add_factory02_dispatch_office import LAYOUT_ID, SITE, STORE
from tools.add_factory02_cafeteria import TABLE, CHAIR, KITCHEN, PREFIX as FURNITURE_PREFIX
from tools.add_factory02_parking_office import boundary, hashes, write_json, verify_native_candidate
from tools.audit_independent_factory_layer2 import footprint, marking_polygon

BASE = '566135d22db2800912ed3ef19e313ca17b7be1d8455d83247b70da6e6a12b4d6'
PREFIX = 'pl-lunchroom-'
REMOVED_WALLS = {'pl-parking-office-wall-factory-upper','pl-parking-office-wall-office-north'}
OLD_ROUTES = {'rt-independent-cafeteria-walk','rt-independent-kitchen-entrance'}
EDITED_ZONES = {'zn-independent-cafeteria','zn-independent-cafeteria-kitchen','zn-parking-office-extension'}
ROOM = (300.01464,28.32,334,61)
FLOOR = (300.01464,28.5,334,61)
KITCHEN_BOUNDS = (324.8,52,332,58.6)
RESERVE = (324.8,31.4,332,42.8)
TABLE_CENTERS = [(x,z) for z in (32.9,37.1,41.3,47.1,51.3,55.5) for x in (304.4,308.4,316.4,320.4)]
FUTURE_CENTERS = [(x,z) for z in (32.9,37.1,41.3) for x in (326.3,330.3)]
ROUTES = [
    ('factory','Lunchroom Factory Entrance',[(297,44.2),(332,44.2)],2.0),
    ('office','Office to Lunchroom',[(323,19),(323,26.7),(313.25,26.7),(313.25,30.5)],1.4),
    ('dining','Lunchroom Central Aisle',[(313.25,30.5),(313.25,58)],2.0),
    ('kitchen','Kitchen Serving Access',[(322.7,44.2),(322.7,55.3),(325.7,55.3)],1.2),
]


def wall_specs():
    panels = [
        ('factory-lower',(299.76464,20,300.01464,43),6),
        ('factory-upper',(299.76464,45.4,300.01464,91),6),
        ('office-shared-left',(302,28.32,312.25,28.5),3),
        ('office-shared-right',(314.25,28.32,325,28.5),3),
        ('south-west',(300.03464,28.32,301.98,28.5),3),
        ('south-east',(325.02,28.32,333.8,28.5),3),
        ('east',(333.82,28.52,334,60.8),3),
        ('north',(300.03464,60.82,334,61),3),
    ]
    specs=[]
    for key,(x0,z0,x1,z1),height in panels:
        specs.append(dict(assetId='asset-factory02-perimeter-lunch-'+key,
            displayName='Lunchroom wall - '+key,category='Building Structures',
            dimensions=dict(width=x1-x0,depth=z1-z0,height=height),
            artifact=f'generated/industrial_assets/factory02_lunchroom/{key}/model.glb',
            description='Authored concept partition; no structural or fire qualification.',
            tags=['wall','perimeter','lunchroom'],
            source=dict(kind='authored-primitive',generator=Path(__file__).name),
            sourceToCanonical=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]))
    return panels,specs


def paint_exclusions():
    return [LineString([(a[0],a[1]),(b[0],b[1])]).buffer(width/2,cap_style=2)
            for _,_,points,width in ROUTES for a,b in zip(points,points[1:])]


def rectangle_tiles(bounds, exclusions):
    x0,z0,x1,z1=bounds
    clipped=[p for p in exclusions if p.intersects(box(*bounds))]
    xs=sorted({x0,x1}|{x for p in clipped for x in (p.bounds[0],p.bounds[2]) if x0<x<x1})
    zs=sorted({z0,z1}|{z for p in clipped for z in (p.bounds[1],p.bounds[3]) if z0<z<z1})
    blocked=unary_union(clipped)
    return [(a,c,b,d) for a,b in zip(xs,xs[1:]) for c,d in zip(zs,zs[1:])
            if box(a,c,b,d).intersection(blocked).area<1e-8]


def operations(before,catalog):
    if before['layoutId']!=LAYOUT_ID or layout_revision(before)!=BASE:
        raise ValueError('Factory 02 changed; review the saved revision before expanding.')
    original={p['placementId']:p for p in before['placements']}
    assert REMOVED_WALLS <= set(original)
    assert len([p for p in original if p.startswith(FURNITURE_PREFIX)])==21
    ops=[]
    for pid in sorted(REMOVED_WALLS):
        ops.append(dict(op='delete_placement',placementId=pid))
    for rid in sorted(OLD_ROUTES):
        ops.append(dict(op='delete_route',routeId=rid))

    def zone(zid,label,bounds,color):
        ops.append(dict(op='add_zone',zone=dict(zoneId=zid,label=label,zoneType='workcell',
            boundary=boundary(bounds),floorElevation=0,anchors=[],evidence=[],
            extensions=dict(style=dict(fillColor=color)))))

    ops.extend([
        dict(op='edit_zone',zoneId='zn-independent-cafeteria',patch=dict(
            label='Employee Lunchroom - 96 Dining Seats',boundary=boundary(ROOM))),
        dict(op='edit_zone',zoneId='zn-independent-cafeteria-kitchen',patch=dict(
            label='Lunchroom Kitchen + Serving',boundary=boundary(KITCHEN_BOUNDS))),
        dict(op='edit_zone',zoneId='zn-parking-office-extension',patch=dict(
            label='Office + Lunchroom + Parking')),
    ])
    zone('zn-lunchroom-reserve','Future Seating - 6 Tables / 24 Seats',RESERVE,'#c5d9c9')
    zone('zn-lunchroom-return','Return + Handwash',(324.8,47,332,50.8),'#b6c8cf')

    def place(pid,aid,x,z,label,yaw=0,locked=False):
        asset=catalog[aid]
        if not asset['definition']['readiness']['placementReady']['value']:
            raise ValueError(f'{aid} is not placement-ready')
        q=dict(x=0,y=math.sin(yaw/2),z=0,w=math.cos(yaw/2))
        if pid in original:
            assert original[pid]['assetId']==aid
            ops.append(dict(op='move_placement',placementId=pid,movementKind='user',position=dict(x=x,y=0,z=z)))
            if q!=original[pid]['transform']['quaternion']:
                ops.append(dict(op='rotate_placement',placementId=pid,movementKind='user',quaternion=q))
        else:
            ops.append(dict(op='place_asset',placement=dict(placementId=pid,assetId=aid,
                assetDefinitionRevision=asset['assetDefinitionRevision'],
                transform=dict(position=dict(x=x,y=0,z=z),quaternion=q,scale=1),
                positionMode='locked' if locked else 'manual',snapRelationship=None,
                metadata=dict(instanceLabel=label,inputMethod='independent-authoring'))))

    for number,(x,z) in enumerate(TABLE_CENTERS,1):
        pid=FURNITURE_PREFIX+f'table-{number}'
        place(pid,TABLE,x,z,f'Lunchroom Table {number:02}')
        for side,(dx,dz) in enumerate(((0,-1.15),(1.15,0),(0,1.15),(-1.15,0)),1):
            place(pid+f'-chair-{side}',CHAIR,x+dx,z+dz,f'Table {number:02} Chair {side}',math.atan2(-dx,-dz))
    # Local +X is the kitchen island/serving side; turn it toward dining (-X).
    place(FURNITURE_PREFIX+'kitchen',KITCHEN,328.3,55.3,'Lunchroom Kitchen',math.pi)
    place(PREFIX+'waste-1','asset-green-garbage-container',326,49.6,'Waste Return 1')
    place(PREFIX+'waste-2','asset-green-garbage-container',327.2,49.6,'Waste Return 2')
    place(PREFIX+'handwash','asset-user-library-sink-1',330,49.6,'Handwash Sink')
    for key,b,height in wall_specs()[0]:
        x0,z0,x1,z1=b
        place(PREFIX+'wall-'+key,'asset-factory02-perimeter-lunch-'+key,(x0+x1)/2,(z0+z1)/2,
              'Lunchroom '+key+' wall',locked=True)
    ops.append(dict(op='set_perimeter_walls',wallSettings=dict(boundarySource='polygon',
        boundary=boundary(KITCHEN_BOUNDS),heightMeters=2.8,thicknessMeters=.15,
        openings=[dict(edge=3,startMeters=1.3,endMeters=5.3)])))
    for key,label,points,width in ROUTES:
        ops.append(dict(op='add_aisle',routeId='rt-lunchroom-'+key,aisle=dict(
            label=label,centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,
            aisleKind='pedestrian',direction='two_way',color='#62becb',clearanceEvidenceStatus='unverified')))

    def paint(key,kind,bounds,color,text='',y=.008):
        x0,z0,x1,z1=bounds
        ops.append(dict(op='add_floor_marking',floorMarking=dict(
            markingId='fm-lunchroom-'+key,markingType=kind,label=key.replace('-',' ').title(),
            semanticRole='decorative',transform=dict(position=dict(x=(x0+x1)/2,y=y,z=(z0+z1)/2),rotationDegrees=0),
            width=x1-x0,depth=z1-z0,fillColor=color,strokeColor=color,opacity=1,text=text,
            positionMode='manual',metadata=dict(authoredIn='lunchroom_expansion'),evidence=[])))

    exclusions=paint_exclusions()
    for i,b in enumerate(rectangle_tiles(FLOOR,exclusions)):
        paint(f'000-floor-{i:03}','solid_line',b,'#d4dfdb',y=0)
    removed_paint=[]
    for mark in before['floorMarkings']:
        if mark['markingId'].startswith('fm-parking-office-000-office-floor-'):
            cuts=exclusions
        elif mark['markingId'].startswith('fm-parking-office-000-asphalt-'):
            cuts=[box(*FLOOR)]
        else:
            continue
        shape=marking_polygon(mark)
        if not any(shape.intersection(p).area>1e-8 for p in cuts):
            continue
        removed_paint.append(mark['markingId'])
        ops.append(dict(op='delete_floor_marking',markingId=mark['markingId']))
        for index,b in enumerate(rectangle_tiles(shape.bounds,cuts)):
            paint(f'000-ground-repair-{len(removed_paint):02}-{index:02}','solid_line',b,mark['fillColor'],y=0)
    paint('title','floor_text',(302,58.7,321,59.6),'#264b48','EMPLOYEE LUNCHROOM - 96 SEATS')
    paint('reserve','floor_text',(325,35.8,331.8,37.2),'#38624e','FUTURE SEATING')
    paint('reserve-count','floor_text',(325,37.3,331.8,38),'#38624e','6 TABLES / 24 SEATS')
    paint('return','floor_text',(325,47.5,331.8,48.2),'#264b48','RETURN + HANDWASH')
    paint('kitchen','floor_text',(325,59,331.8,59.7),'#264b48','KITCHEN / SERVING')
    return ops,removed_paint


def audit(before,after,catalog,removed_paint):
    furniture=[p for p in after['placements'] if p['placementId'].startswith(FURNITURE_PREFIX)]
    assert sum(p['assetId']==TABLE for p in furniture)==24
    assert sum(p['assetId']==CHAIR for p in furniture)==96
    assert sum(p['assetId']==KITCHEN for p in furniture)==1
    changed=[p for p in after['placements'] if p['placementId'].startswith((FURNITURE_PREFIX,PREFIX))]
    shapes={p['placementId']:footprint(p,catalog[p['assetId']]) for p in after['placements']}
    for p in changed:
        for q in after['placements']:
            if p['placementId']!=q['placementId']:
                assert shapes[p['placementId']].intersection(shapes[q['placementId']]).area<1e-8,(p['placementId'],q['placementId'])
    old_room=box(53.5,17,63,36.5)
    assert all(shapes[p['placementId']].intersection(old_room).area<1e-8 for p in furniture)
    assert all(box(*ROOM).covers(shapes[p['placementId']]) for p in furniture)
    corridors=unary_union(paint_exclusions())
    for p in changed:
        assert corridors.intersection(shapes[p['placementId']]).area<1e-8,p['placementId']
    by_id={p['placementId']:p for p in furniture}
    for p in furniture:
        if p['assetId']!=CHAIR:continue
        table=by_id[p['placementId'].rsplit('-chair-',1)[0]]['transform']['position']
        pos,q=p['transform']['position'],p['transform']['quaternion']
        dx,dz=table['x']-pos['x'],table['z']-pos['z']
        length=math.hypot(dx,dz)
        assert math.isclose(2*q['y']*q['w'],dx/length,abs_tol=1e-7)
        assert math.isclose(1-2*q['y']**2,dz/length,abs_tol=1e-7)
    # Check reserved capacity using the same table/chair footprints, without placing them.
    future=[]
    templates=[by_id[FURNITURE_PREFIX+'table-1']]+[by_id[FURNITURE_PREFIX+f'table-1-chair-{i}'] for i in range(1,5)]
    for x,z in FUTURE_CENTERS:
        for template in templates:
            p=deepcopy(template)
            p['transform']['position']['x']+=x-TABLE_CENTERS[0][0]
            p['transform']['position']['z']+=z-TABLE_CENTERS[0][1]
            shape=footprint(p,catalog[p['assetId']])
            assert box(*RESERVE).covers(shape)
            assert all(shape.intersection(s).area<1e-8 for s in list(shapes.values())+future+[corridors])
            future.append(shape)
    def unchanged(field,idfield,allowed):
        previous={v[idfield]:v for v in before[field] if v[idfield] not in allowed}
        current={v[idfield]:v for v in after[field] if v[idfield] in previous}
        assert current==previous,field+' unrelated records changed'
    permitted_placements=REMOVED_WALLS|{p['placementId'] for p in before['placements'] if p['placementId'].startswith(FURNITURE_PREFIX)}
    unchanged('placements','placementId',permitted_placements)
    unchanged('zones','zoneId',EDITED_ZONES)
    unchanged('routes','routeId',OLD_ROUTES)
    unchanged('floorMarkings','markingId',set(removed_paint))
    for key in before['extensions']:
        if key!='facilityPerimeterWalls':assert before['extensions'][key]==after['extensions'][key]
    for key in set(before)-{'placements','zones','routes','floorMarkings','extensions','updatedAt'}:
        assert before[key]==after[key],key
    return dict(tables=24,diningSeats=96,kitchenAssemblies=1,reservedTables=6,reservedSeats=24,
        relocatedExistingFurniture=21,existingFurnitureIdsPreserved=True,
        factoryEntranceWidthMeters=2.4,officeEntranceWidthMeters=2.0,
        officeCubiclesPreserved=10,parkedCarsPreserved=20,motionProgramsPreserved=40,
        newPlacementCount=len(after['placements'])-len(before['placements']),
        oldCafeteriaCleared=True,unrelatedContentPreserved=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--publish-assets',action='store_true')
    parser.add_argument('--publish-layout',action='store_true')
    parser.add_argument('--native-report',type=Path)
    args=parser.parse_args()
    out=args.output.resolve()
    directory=STORE/'layouts/local/site-local/layouts'
    target=directory/(LAYOUT_ID+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    if args.publish_assets or args.publish_layout:
        report=json.loads((out/'report.json').read_text())
        assert report['status'] in {'validated','assets-published'}
        assert target.read_bytes()==(out/'before.json').read_bytes(),'Saved base changed'
        staged=out/'staged-project'
        payload=(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
        if args.publish_assets:
            assert manifest.read_bytes()==(out/'catalog-before.json').read_bytes()
            for spec in wall_specs()[1]:
                dest=ROOT/spec['artifact']
                assert not dest.exists()
                dest.parent.mkdir(parents=True,exist_ok=True)
                RevisionedAuthorityRepository._atomic_write(dest,(staged/spec['artifact']).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,payload)
            report['status']='assets-published'
        else:
            assert report['status']=='assets-published' and manifest.read_bytes()==payload
            assert args.native_report,'Native evidence is required'
            candidate=json.loads((out/'candidate.json').read_text())
            assert layout_revision(candidate)==report['candidateRevision']
            staged_bytes=(out/'validation-store/layouts/local/site-local/layouts'/target.name).read_bytes()
            verify_native_candidate(json.loads(args.native_report.read_text()),candidate,staged_bytes)
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:saved=host.service.save_layout(host.principal(),SITE,LAYOUT_ID,candidate,BASE)
            finally:host.close()
            normalized=deepcopy(saved['layout']);normalized['updatedAt']=candidate['updatedAt']
            assert normalized==candidate
            write_json(out/'saved.json',saved['layout'])
            report.update(status='saved',savedRevision=saved['revision'],nativeEvidencePath=str(args.native_report.resolve()))
            assert {k:v for k,v in hashes(directory).items() if k!=target.name}=={k:v for k,v in report['layoutHashes'].items() if k!=target.name}
        write_json(out/'report.json',report)
        print(json.dumps({k:report[k] for k in ('status','tables','diningSeats')}))
        return
    out.mkdir(parents=True,exist_ok=False)
    before_bytes=target.read_bytes();before=json.loads(before_bytes)
    assert layout_revision(before)==BASE
    (out/'before.json').write_bytes(before_bytes)
    (out/'catalog-before.json').write_bytes(manifest.read_bytes())
    catalog_doc=json.loads(manifest.read_text());existing={a['assetId']:a for a in catalog_doc['assets']}
    specs=wall_specs()[1];present=[s for s in specs if s['assetId'] in existing]
    assert len(present) in {0,len(specs)} and all(existing[s['assetId']]==s for s in present)
    catalog_doc['assets'].extend(s for s in specs if s['assetId'] not in existing)
    catalog_doc['summary']['total']=len(catalog_doc['assets'])
    staged=out/'staged-project';write_json(staged/PRIVATE_ASSET_MANIFEST,catalog_doc)
    for a in specs:
        d=a['dimensions'];dest=Path(_native_fs_path(staged/a['artifact']))
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(build_aabb_proxy_glb(dict(minimum=dict(x=-d['width']/2,y=0,z=-d['depth']/2),
            maximum=dict(x=d['width']/2,y=d['height'],z=d['depth']/2))))
    stage=out/'validation-store'
    copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'))
    copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'))
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops,removed_paint=operations(before,catalog)
        result=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks=audit(before,result,catalog,removed_paint)
        principal=host.principal()
        deps=host.service.validate_dependencies(principal,SITE,result).to_dict()
        spatial=host.service._diagnose_spatial(principal,SITE,result)
        routing=host.service._diagnose_routing(principal,SITE,result)
        write_json(out/'validation.json',dict(dependencies=deps,spatial=spatial,routing=routing))
        host.service._require_spatially_valid(spatial);host.service._require_routing_valid(routing)
        saved=host.service.save_layout(principal,SITE,LAYOUT_ID,result,BASE)
        write_json(out/'candidate.json',saved['layout']);write_json(out/'operations.json',ops)
        report=dict(status='assets-published' if present else 'validated',baseRevision=BASE,
            candidateRevision=saved['revision'],**checks,totalPlacements=len(result['placements']),
            layoutHashes=hashes(directory),spatialMetrics=spatial['metrics'],
            modifiedGroundPaintIds=removed_paint,
            limitations=['96 dining chairs; original kitchen-island stools are not included in that count.',
                'Concept layout, not food-service, fire, accessibility, utility or occupancy approval.',
                'Reserved six-table area remains unfurnished. Kitchen utilities are not routed.'])
        write_json(out/'report.json',report)
        print(json.dumps({k:report[k] for k in ('status','tables','diningSeats','totalPlacements','spatialMetrics')}))
    finally:host.close()


if __name__=='__main__':main()
