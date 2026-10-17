"""Stage a revision-guarded parking/office extension using existing layout APIs."""
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
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path, RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb
from tools.add_factory02_dispatch_office import LAYOUT_ID, SITE, STORE
from tools.audit_independent_factory_layer2 import footprint

BASE = 'c48850962eb6a7fa83c4d4ec41a530466baab490c6c76ab3f2073a6c63da3b4d'
PREFIX = 'pl-parking-office-'
CAR_IDS = ('asset-import-car-93', 'asset-import-tesla-roadster')
CUBICLE = 'asset-import-cubicle'
CHAIR = 'asset-chair-black'
REPLACED_WALL = 'pl-independent-wall-east-south'
WHITE = '#ffffff'
YELLOW = '#facc15'


def write_json(path, value):
    path = Path(_native_fs_path(path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True), encoding='utf-8')


def boundary(bounds):
    x0, z0, x1, z1 = bounds
    return [dict(x=x0,z=z0),dict(x=x1,z=z0),dict(x=x1,z=z1),dict(x=x0,z=z1)]


def primitives():
    # Split panels leave actual collision-free entrances; no painted fake doorway.
    walls = [
        ('factory-lower', (299.76464,.26,300.01464,18),6),
        ('factory-upper', (299.76464,20,300.01464,91),6),
        ('office-south', (302,10,325,10.18),3),
        ('office-north', (302,28.32,325,28.5),3),
        ('office-west-lower', (302,10.2,302.18,18),3),
        ('office-west-upper', (302,20,302.18,28.3),3),
        ('office-east-lower', (324.82,10.2,325,18),3),
        ('office-east-upper', (324.82,20,325,28.3),3),
    ]
    specs = []
    for key, b, h in walls:
        x0,z0,x1,z1 = b
        specs.append(dict(assetId='asset-factory02-perimeter-annex-'+key,
            displayName='Factory 02 office extension wall - '+key,
            category='Building Structures', dimensions=dict(width=x1-x0,depth=z1-z0,height=h),
            artifact=f'generated/industrial_assets/factory02_parking_office/{key}/model.glb',
            description='Authored concept wall panel; not structural or fire approval.',
            tags=['wall','perimeter','office','authored'],
            source=dict(kind='authored-primitive',generator=Path(__file__).name)))
    specs.append(dict(assetId='asset-factory02-parking-wheel-stop',
        displayName='Parking Wheel Stop',category='Building Structures',
        dimensions=dict(width=1.6,depth=.16,height=.14),
        artifact='generated/industrial_assets/factory02_parking_office/wheel-stop/model.glb',
        description='Authored 1.6 m parking wheel-stop concept.',tags=['parking','wheel stop'],
        source=dict(kind='authored-primitive',generator=Path(__file__).name)))
    for spec in specs:
        spec['sourceToCanonical'] = [1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]
    return walls, specs


def operations(before, catalog):
    if before['layoutId'] != LAYOUT_ID or layout_revision(before) != BASE:
        raise ValueError('Factory 02 changed; review the new revision before authoring.')
    settings = deepcopy(before['extensions']['facilityPlan'])
    settings['widthMeters'] = 376.0
    ops = [dict(op='set_plan_settings',planSettings=settings),
           dict(op='delete_placement',placementId=REPLACED_WALL)]

    def zone(key,label,b,color):
        ops.append(dict(op='add_zone',zone=dict(zoneId='zn-parking-office-'+key,
            label=label,zoneType='workcell',boundary=boundary(b),floorElevation=0,
            anchors=[],evidence=[],extensions=dict(style=dict(fillColor=color)))))

    def place(key,aid,x,z,label,yaw=0,locked=False):
        asset = catalog[aid]
        if not asset['definition']['readiness']['placementReady']['value']:
            raise ValueError(f'{aid} is not placement-ready')
        half = math.radians(yaw)/2
        ops.append(dict(op='place_asset',placement=dict(placementId=PREFIX+key,
            assetId=aid,assetDefinitionRevision=asset['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=0,z=z),
                quaternion=dict(x=0,y=math.sin(half),z=0,w=math.cos(half)),scale=1),
            positionMode='locked' if locked else 'manual',snapRelationship=None,
            metadata=dict(instanceLabel=label,inputMethod='independent-authoring'))))

    def paint(key,kind,x,z,w,d,color=WHITE,text='',rotation=0,role='decorative',y=.008):
        ops.append(dict(op='add_floor_marking',floorMarking=dict(
            markingId='fm-parking-office-'+key,markingType=kind,label=key.replace('-',' ').title(),
            semanticRole=role,transform=dict(position=dict(x=x,y=y,z=z),rotationDegrees=rotation),
            width=w,depth=d,fillColor=color,strokeColor=color,opacity=1,text=text,
            positionMode='manual',metadata=dict(authoredIn='parking_office_extension'),evidence=[])))

    def aisle(key,label,points,width,kind='pedestrian',color='#62becb'):
        ops.append(dict(op='add_aisle',routeId='rt-parking-office-'+key,aisle=dict(label=label,
            centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,
            aisleKind=kind,direction='two_way',color=color,clearanceEvidenceStatus='unverified')))

    zone('extension','Office + Parking Extension',(299.75,0,376,96),'#cbd5db')
    zone('office','Administrative Office - 10 Cubicles',(302,10,325,28.5),'#c2d2db')
    zone('parking','Employee Parking - 20 Spaces',(328,5,374,30),'#525d66')
    # Keep ground surfaces disjoint from the route paint instead of stacking
    # nearly coplanar meshes, which flicker at the factory camera's depth range.
    paths = [box(297,18.2,329.8,19.8),box(296.2,19,297.8,93),
             box(294,92.2,297,93.8),box(329,6.6,330.6,27.4),
             box(329.8,26.6,362.7,28.2)]
    surfaces = [
        ('000-asphalt',(328,5,374,30),'#343c43'),
        ('000-office-floor',(302,10,325,28.5),'#d9e0e4'),
        ('001-sidewalk-top',(328,26.4,364.5,28.4),'#b7c5ce'),
        ('001-sidewalk-bottom',(328,5.6,364.5,7.6),'#b7c5ce'),
    ]
    for index,(key,b,color) in enumerate(surfaces):
        exclusions=paths+[box(*s[1]) for s in surfaces[index+1:]]
        shape=box(*b)
        exclusions=[p for p in exclusions if p.intersects(shape)]
        xs=sorted({b[0],b[2]}|{x for p in exclusions for x in (p.bounds[0],p.bounds[2]) if b[0]<x<b[2]})
        zs=sorted({b[1],b[3]}|{z for p in exclusions for z in (p.bounds[1],p.bounds[3]) if b[1]<z<b[3]})
        blocked=unary_union(exclusions)
        tile=0
        for x0,x1 in zip(xs,xs[1:]):
            for z0,z1 in zip(zs,zs[1:]):
                cell=box(x0,z0,x1,z1)
                if cell.intersection(blocked).area>1e-8:
                    continue
                paint(f'{key}-{tile:03}','solid_line',(x0+x1)/2,(z0+z1)/2,x1-x0,z1-z0,color,y=0)
                tile+=1
    for key,b,h in primitives()[0]:
        x0,z0,x1,z1 = b
        place('wall-'+key,'asset-factory02-perimeter-annex-'+key,(x0+x1)/2,(z0+z1)/2,
              key.replace('-',' ').title()+' wall',locked=True)

    for row,z in enumerate((14.7,23.7)):
        for column in range(5):
            number = row*5+column+1
            x = 305.3+3.9*column
            # Open face points into the central circulation zone.
            yaw = 0 if row==0 else 180
            place(f'cubicle-{number:02}',CUBICLE,x,z,f'Office Cubicle {number:02}',yaw)
            chair_z = z+(1.45 if row==0 else -1.45)
            place(f'chair-{number:02}',CHAIR,x,chair_z,f'Office Chair {number:02}',180 if row==0 else 0)
            paint(f'office-number-{number:02}','floor_text',x,z+(2.05 if row==0 else -2.05),1.2,.35,
                  '#334155',f'C{number:02}')

    stalls = []
    # Two 3.4 m accessible bays share a 2 m access strip. Remaining bays are ordinary.
    x = 331.5
    for index in range(10):
        width = 3.4 if index<2 else 2.8
        stalls.append(dict(number=index+1,x=x+width/2,z=23.2,width=width,depth=5.8,accessible=index<2))
        x += width+(2.0 if index==0 else 0)
    for index in range(10):
        stalls.append(dict(number=index+11,x=331.5+(index+.5)*3.12,z=10.9,width=3.12,depth=5.8,accessible=False))
    for stall in stalls:
        n,x,z,w,d = (stall[k] for k in ('number','x','z','width','depth'))
        low = n>10
        aid = CAR_IDS[(n-1)%2]
        place(f'car-{n:02}',aid,x,z,f'Parking {n:02} - '+catalog[aid]['displayName'],180 if low else 0)
        paint(f'bay-{n:02}','parking_box',x,z,w,d,WHITE,str(n).zfill(2),role='parking')
        edge = z+(d/2 if low else -d/2)
        paint(f'number-{n:02}','floor_text',x,edge+(.4 if low else -.4),.8,.45,WHITE,str(n).zfill(2))
        head = z+(-2.68 if low else 2.68)
        place(f'wheel-stop-{n:02}','asset-factory02-parking-wheel-stop',x,head,f'Wheel Stop {n:02}',locked=True)
        if stall['accessible']:
            paint(f'accessible-blue-{n}','solid_line',x,19.85,1.0,.58,'#126cc4')
            paint(f'accessible-symbol-{n}','floor_text',x,19.85,.9,.55,WHITE,'\u267f',y=.012)
    paint('access-strip','keep_clear',335.9,23.2,2.0,5.8,WHITE,'NO PARKING',role='keep_clear')
    # Clip each diagonal stripe to the shared access rectangle.
    access = box(334.9,20.3,336.9,26.1)
    for n in range(11):
        s = LineString([(334.9,19.0+n*.7),(336.9,21.0+n*.7)]).intersection(access)
        if s.is_empty or s.length<.05:
            continue
        a,b = list(s.coords)[0],list(s.coords)[-1]
        paint(f'access-hatch-{n:02}','solid_line',(a[0]+b[0])/2,(a[1]+b[1])/2,.10,s.length,
              WHITE,rotation=math.degrees(math.atan2(b[0]-a[0],b[1]-a[1])),role='keep_clear')
    paint('center-line','dashed_line',349.5,17.05,.12,34,YELLOW,rotation=90)
    for n,x in enumerate((338,349,359)):
        paint(f'arrow-west-{n}','direction_arrow',x,18.45,.7,1.7,WHITE,rotation=-90)
        paint(f'arrow-east-{n}','direction_arrow',x,15.65,.7,1.7,WHITE,rotation=90)
    paint('crosswalk','crosswalk',329.8,17.05,1.8,6.5,WHITE,role='pedestrian_lane')
    paint('stop-line','solid_line',371.4,15.65,.22,2.8,WHITE)
    paint('stop-text','floor_text',369.8,15.65,2,1,WHITE,'STOP',rotation=90)
    paint('parking-title','floor_text',349,29.3,12,.7,WHITE,'EMPLOYEE PARKING - 20 SPACES')
    paint('office-title','floor_text',313.5,26.8,12,.6,'#334155','ADMINISTRATIVE OFFICE')
    aisle('office-walk','Office Central Aisle',[(297,19),(329.8,19)],1.6)
    aisle('factory-walk','Office to Factory Pedestrian Link',[(297,19),(297,93),(294,93)],1.6)
    aisle('parking-walk','Parking Pedestrian Connection',[(329.8,6.6),(329.8,27.4),(362.7,27.4)],1.6)
    # Parking circulation is painted geometry, not a manufacturing transfer route.
    return ops, stalls


def audit(before,after,catalog,stalls):
    added = [p for p in after['placements'] if p['placementId'].startswith(PREFIX)]
    cars = [p for p in added if p['placementId'].startswith(PREFIX+'car-')]
    assert len(cars)==20 and {p['assetId'] for p in cars}==set(CAR_IDS)
    assert all(p['transform']['scale']==1 for p in cars)
    assert len([p for p in added if p['assetId']==CUBICLE])==10
    assert len([p for p in added if p['assetId']==CHAIR])==10
    shapes = {p['placementId']:footprint(p,catalog[p['assetId']]) for p in after['placements']}
    for s in stalls:
        car = shapes[PREFIX+f"car-{s['number']:02}"]
        bay = box(s['x']-s['width']/2,s['z']-2.9,s['x']+s['width']/2,s['z']+2.9)
        assert bay.covers(car)
        assert car.distance(bay.boundary)>.2
    access = box(334.9,20.3,336.9,26.1)
    assert all(not access.intersects(shapes[p['placementId']]) for p in cars)
    drive = box(331.5,13.8,374,20.3)
    assert all(drive.intersection(shapes[p['placementId']]).area<1e-8 for p in added)
    for p in added:
        for q in after['placements']:
            if p['placementId']==q['placementId']:
                continue
            assert shapes[p['placementId']].intersection(shapes[q['placementId']]).area<1e-8, (p['placementId'],q['placementId'])
    restored = deepcopy(after)
    restored['placements'] = [p for p in after['placements'] if not p['placementId'].startswith(PREFIX)]
    index = next(i for i,p in enumerate(before['placements']) if p['placementId']==REPLACED_WALL)
    restored['placements'].insert(index,deepcopy(before['placements'][index]))
    for field,prefix,idfield in [('zones','zn-parking-office-','zoneId'),('routes','rt-parking-office-','routeId'),('floorMarkings','fm-parking-office-','markingId')]:
        restored[field] = [p for p in restored[field] if not p[idfield].startswith(prefix)]
    restored['extensions']['facilityPlan'] = deepcopy(before['extensions']['facilityPlan'])
    restored['updatedAt'] = before['updatedAt']
    assert restored==before, 'Unrelated layout content changed'
    return dict(cars=20,cubicles=10,chairs=10,wheelStops=20,
        fullScaleCarsOnly=True,accessibleSpaces=2,standardSpaces=18,
        driveAisleWidthMeters=6.5,sharedAccessAisleWidthMeters=2,
        officeDoorWidthMeters=2,siteWidthMeters=376,
        unchangedExistingPlacements=len(before['placements'])-1,
        replacedWall=REPLACED_WALL,existingMotionAndKitchenPreserved=True,
        carAssetIds=list(CAR_IDS),addedPlacements=len(added))


def hashes(directory):
    return {p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.glob('*.json') if p.name!='registry.json'}


def verify_native_candidate(native, candidate, staged_bytes):
    assert native['status']=='passed', 'Native acceptance required'
    assert native['candidateHash']==hashlib.sha256(staged_bytes).hexdigest(), 'Reviewed store bytes changed'
    # The repository and readable export have different JSON whitespace.
    assert json.loads(staged_bytes)==candidate, 'Candidate differs from reviewed document'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--publish-assets',action='store_true')
    parser.add_argument('--publish-layout',action='store_true')
    parser.add_argument('--native-report',type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    directory = STORE/'layouts/local/site-local/layouts'
    target = directory/(LAYOUT_ID+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    if args.publish_assets or args.publish_layout:
        report = json.loads((out/'report.json').read_text())
        assert report['status'] in {'validated','assets-published'}
        assert target.read_bytes()==(out/'before.json').read_bytes(), 'Saved base changed'
        staged = out/'staged-project'
        payload = (staged/PRIVATE_ASSET_MANIFEST).read_bytes()
        if args.publish_assets:
            assert manifest.read_bytes()==(out/'catalog-before.json').read_bytes()
            for spec in primitives()[1]:
                dest = ROOT/spec['artifact']
                assert not dest.exists(), dest
                dest.parent.mkdir(parents=True,exist_ok=True)
                RevisionedAuthorityRepository._atomic_write(dest,(staged/spec['artifact']).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,payload)
            report['status']='assets-published'
        else:
            assert report['status']=='assets-published' and manifest.read_bytes()==payload
            native_path = args.native_report or out.parent/'native01/report.json'
            native = json.loads(native_path.read_text())
            candidate = json.loads((out/'candidate.json').read_text())
            assert layout_revision(candidate)==report['candidateRevision']
            staged_bytes=(out/'validation-store/layouts/local/site-local/layouts'/target.name).read_bytes()
            verify_native_candidate(native,candidate,staged_bytes)
            live = LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                saved = live.service.save_layout(live.principal(),SITE,LAYOUT_ID,candidate,BASE)
            finally:
                live.close()
            write_json(out/'saved.json',saved['layout'])
            report.update(status='saved',savedRevision=saved['revision'],
                          nativeEvidencePath=str(native_path.resolve()))
            current = hashes(directory)
            assert {k:v for k,v in current.items() if k!=target.name}=={k:v for k,v in report['layoutHashes'].items() if k!=target.name}
        write_json(out/'report.json',report)
        print(json.dumps({k:report[k] for k in ('status','cars','cubicles','chairs')}))
        return
    out.mkdir(parents=True,exist_ok=False)
    before_bytes = target.read_bytes()
    before = json.loads(before_bytes)
    assert layout_revision(before)==BASE
    (out/'before.json').write_bytes(before_bytes)
    (out/'catalog-before.json').write_bytes(manifest.read_bytes())
    catalog_doc = json.loads(manifest.read_text())
    specs = primitives()[1]
    existing = {a['assetId']:a for a in catalog_doc['assets']}
    existing_specs = [s for s in specs if s['assetId'] in existing]
    assert all(existing[s['assetId']]==s for s in existing_specs), 'Conflicting authored asset definition'
    assert len(existing_specs) in {0,len(specs)}, 'Partial asset publication needs review'
    catalog_doc['assets'].extend(s for s in specs if s['assetId'] not in existing)
    catalog_doc['summary']['total']=len(catalog_doc['assets'])
    staged = out/'staged-project'
    write_json(staged/PRIVATE_ASSET_MANIFEST,catalog_doc)
    for asset in specs:
        d=asset['dimensions']
        bounds=dict(minimum=dict(x=-d['width']/2,y=0,z=-d['depth']/2),maximum=dict(x=d['width']/2,y=d['height'],z=d['depth']/2))
        dest=staged/asset['artifact']
        dest.parent.mkdir(parents=True,exist_ok=True)
        dest.write_bytes(build_aabb_proxy_glb(bounds))
    stage = out/'validation-store'
    copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'))
    copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'))
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops,stalls=operations(before,catalog)
        candidate=apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks=audit(before,candidate,catalog,stalls)
        principal=host.principal()
        deps=host.service.validate_dependencies(principal,SITE,candidate).to_dict()
        spatial=host.service._diagnose_spatial(principal,SITE,candidate)
        routing=host.service._diagnose_routing(principal,SITE,candidate)
        write_json(out/'validation.json',dict(dependencies=deps,spatial=spatial,routing=routing))
        host.service._require_spatially_valid(spatial)
        host.service._require_routing_valid(routing)
        saved=host.service.save_layout(principal,SITE,LAYOUT_ID,candidate,BASE)
        write_json(out/'candidate.json',saved['layout'])
        write_json(out/'operations.json',ops)
        write_json(out/'stalls.json',stalls)
        report=dict(status='assets-published' if existing_specs else 'validated',baseRevision=BASE,candidateRevision=saved['revision'],
            **checks,totalPlacements=len(candidate['placements']),layoutHashes=hashes(directory),
            spatialMetrics=spatial['metrics'],
            limitations=['Concept layout, not a traffic, accessibility, fire or building-code approval.',
                'Cubicle/chair positioning is conceptual; ergonomic reach has not been qualified.',
                'No new car movement programs were authored. Existing 40 factory programs are preserved.'],
            accessibilityReference='https://www.access-board.gov/ada/guides/chapter-5-parking/')
        write_json(out/'report.json',report)
        print(json.dumps({k:report[k] for k in ('status','cars','cubicles','chairs','totalPlacements','spatialMetrics')}))
    finally:
        host.close()


if __name__=='__main__':
    main()
