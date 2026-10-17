"""Build a reviewed Private Gym draft using the existing operation kernel.

--open-sheet publishes only new architectural assets and an EMPTY new sheet.
The desktop review driver authors the equipment into its ordinary unsaved session.
No existing saved layout is modified and no equipment Save is performed here.
"""
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import create_layout_document, apply_facility_layout_operations
from tools.add_factory02_conference_rooms import box_glb, IDENTITY
from tools.brand_factory02_walls import branded_glb
from tools.audit_independent_factory_layer2 import footprint

LAYOUT = 'fl-private-gym-20261007'
STORE = ROOT / '.runtime/facility-layout'
OUT = ROOT / '.runtime/private-gym-20261007'
PLAN = dict(widthMeters=60, depthMeters=30, gridSpacingMeters=.5, majorGridSpacingMeters=5)
WALLS = dict(boundarySource='plan', heightMeters=3.6, thicknessMeters=.18,
             openings=[dict(edge=0, startMeters=5, endMeters=7),
                       dict(edge=1, startMeters=10, endMeters=12),
                       dict(edge=2, startMeters=29, endMeters=31)])
ZONES = [
    ('reception', 'Reception + Social Lounge', (0, 0, 12, 10), '#9bbdc2'),
    ('cardio', 'Cardio - 18 Stations', (12, 0, 36, 10), '#98b8c8'),
    ('functional', 'Functional + Mobility', (36, 0, 54, 10), '#93bbae'),
    ('staff', 'Staff + Storage - Reserved', (54, 0, 60, 10), '#c6cbd0'),
    ('circulation', 'Member Circulation', (0, 10, 60, 12), '#b8c5c8'),
    ('free', 'Free Weights + Racks', (0, 12, 17, 30), '#809ca5'),
    ('lower', 'Lower Body', (17, 12, 31, 30), '#a6b594'),
    ('cable', 'Cable + Multi-Station', (31, 12, 41, 30), '#9db9b6'),
    ('upper', 'Upper + General Strength', (41, 12, 51, 30), '#a9adbf'),
    ('support', 'Changing + Toilets - Reserved', (51, 12, 60, 30), '#bcc3ca'),
]
# Quantities are authored design requirements, not inferred simultaneous capacity.
EQUIPMENT = [
    ('cardio', 'gym-expansion-cybex-710t', [(15+3.5*i, 2.1, 90) for i in range(6)]),
    ('cardio', 'gym-commercial-elliptical', [(15+3.5*i, 6, 180) for i in range(6)]),
    ('cardio', 'gym-commercial-stationary-bike', [(15+3.5*i, 8.5, 180) for i in range(6)]),
    ('free', 'gym-commercial-assembly-asm1', [(3.3, 26.5, 0), (8.7, 26.5, 0)]),
    ('free', 'gym-commercial-smith-machine', [(3.3, 21, 0), (8.7, 21, 0)]),
    ('free', 'gym-multi-station', [(3.3, 15.5, 180), (8.7, 15.5, 180)]),
    ('free', 'gym-bench-press', [(13.4, 15.5, 0), (13.4, 20.5, 180)]),
    ('free', 'gym-dumbbell-rack', [(13.5, 26.7, 0), (15.7, 26.7, 0)]),
    ('free', 'gym-commercial-workout-bench', [(2.3,18.2,0),(5,18.2,0),(7.7,18.2,0),(10.4,18.2,0)]),
    ('free', 'gym-expansion-flat-bench', [(5.9,23.8,0),(10.8,23.8,0)]),
    ('free', 'gym-commercial-triceps', [(12.4,23.7,0),(14.3,23.7,0)]),
    ('lower', 'gym-commercial-booty-blaster', [(19.5,15.4,0),(24,15.4,0)]),
    ('lower', 'gym-commercial-seated-calf', [(19.5,20.8,0),(24,20.8,0)]),
    ('lower', 'gym-expansion-belt-squat', [(20,26.6,0)]),
    ('lower', 'gym-expansion-leg-extension', [(28.3,15.4,90)]),
    ('lower', 'gym-expansion-squat-calf', [(28.3,20.8,0)]),
    ('lower', 'gym-expansion-standing-pendulum-press', [(24.5,26.6,0)]),
    ('lower', 'gym-vertical-leg-press', [(28.7,26.6,0)]),
    ('lower', 'gym-expansion-sissy-squat', [(24,18.1,0)]),
    ('upper', 'gym-commercial-mid-row', [(43.5,15.5,0),(48,15.5,0)]),
    ('upper', 'gym-commercial-incline-lever-row', [(43.5,21,0),(48,21,0)]),
    ('upper', 'gym-commercial-scott-bench', [(43.5,26.5,180),(48,26.5,180)]),
    ('upper', 'gym-commercial-mach1', [(43.5,18.3,0)]),
    ('upper', 'gym-commercial-model', [(48,18.3,0)]),
    ('cable', 'gym-commercial-product1', [(36,15.5,0)]),
    ('cable', 'gym-expansion-hpz-000', [(34,21.3,0)]),
    ('cable', 'gym-x1000', [(38.7,21.3,180)]),
    ('cable', 'gym-commercial-native-multi-gym', [(33.8,26.7,0)]),
    ('cable', 'gym-commercial-multi-gym', [(38.4,26.7,180)]),
    ('functional', 'gym-commercial-power-tower', [(39,2.5,0),(43.5,2.5,0)]),
    ('functional', 'gym-expansion-floor-glute-ham', [(48,2.5,0)]),
    ('functional', 'gym-expansion-hyperextension', [(51.5,2.5,0)]),
    ('functional', 'gym-expansion-abdominal-bench', [(48,7.3,0),(51.5,7.3,0)]),
    ('reception', 'gym-commercial-pool-table', [(3.5,7,0)]),
]
ROUTES = [
    ('spine', [(1,11),(59,11)], 2),
    ('entrance', [(6,1),(6,3.6),(11.2,3.6),(11.2,11)], 1.2),
    ('free', [(11.7,11),(11.7,22)], 1.2),
    ('lower', [(21.8,11),(21.8,24)], 1.2),
    ('cables', [(32,11),(32,18),(36.4,18),(36.4,29)], 1.2),
    ('upper', [(45.8,11),(45.8,29)], 1.2),
    ('functional', [(37,11),(37,5),(52.5,5)], 1.2),
]


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2), encoding='utf-8')


def saved_hashes():
    return {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (STORE/'layouts/local/site-local/layouts').glob('*.json')}


def prepare_assets(out, library):
    specs = {'reception-brand': (8,.15,3.3), 'support-8': (8,.15,3),
             'support-6': (6,.15,3), 'support-3': (3,.15,3)}
    artifacts = []
    for key,(w,d,h) in specs.items():
        dimensions = dict(width=w,depth=d,height=h)
        raw = branded_glb(dimensions, dict(width=4.5,centerX=0,centerY=2.2,face=1))[0] if key=='reception-brand' else box_glb(w,d,h)
        artifact = f'generated/industrial_assets/private_gym/{key}/model.glb'
        target = out/'staged-project'/artifact
        target.parent.mkdir(parents=True,exist_ok=True); target.write_bytes(raw)
        aid = 'asset-private-gym-'+key
        assert not any(a['assetId']==aid for a in library['assets']), 'Architectural asset already exists'
        library['assets'].append(dict(assetId=aid, displayName='Private Gym '+key.replace('-',' ').title(),
            category='Building Structures', dimensions=dimensions, artifact=artifact, sourceToCanonical=IDENTITY,
            tags=['gym','wall','partition'], description='Authored concept partition; construction rating unverified.',
            source=dict(kind='authored-primitive',generator=Path(__file__).name)))
        artifacts.append(artifact)
    library['summary']['total']=len(library['assets'])
    write(out/'staged-project'/PRIVATE_ASSET_MANIFEST,library)
    return artifacts


def build(catalog, blank):
    ops=[]
    def zone(key,label,b,color):
        x0,z0,x1,z1=b
        ops.append(dict(op='add_zone',zone=dict(zoneId='zn-private-gym-'+key,label=label,zoneType='workcell',
            boundary=[dict(x=x0,z=z0),dict(x=x1,z=z0),dict(x=x1,z=z1),dict(x=x0,z=z1)],
            floorElevation=0,anchors=[],evidence=[],extensions=dict(style=dict(fillColor=color)))))
    zone('building','Private Gym - 1,800 m2',(0,0,60,30),'#ccd3d5')
    for key,label,b,color in ZONES: zone(key,label,b,color)
    def place(key,aid,x,z,yaw=0,y=0,role='equipment',color=None):
        aid=aid if aid.startswith('asset-') else 'asset-'+aid
        q=math.radians(yaw)/2
        p=dict(placementId='pl-private-gym-'+key,assetId=aid,assetDefinitionRevision=catalog[aid]['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1),
            positionMode='manual',snapRelationship=None,
            metadata=dict(instanceLabel=key.replace('-',' ').title(),inputMethod='independent-authoring',gymRole=role))
        if color:p['appearance']=dict(color=color)
        ops.append(dict(op='place_asset',placement=p))
    for area,aid,positions in EQUIPMENT:
        for i,(x,z,yaw) in enumerate(positions): place(aid+'-'+str(i+1),aid,x,z,yaw,role='schedule')
    # Loaded bars have dedicated floor-level equipment bays, outside all member paths.
    for key,aid,x,z,yaw in [
        ('feature-wall','private-gym-reception-brand',6,.3,0),
        ('support-west-a','private-gym-support-8',51.2,17,90),
        ('support-west-b','private-gym-support-6',51.2,26.4,90),
        ('support-divider','private-gym-support-8',55.5,22,0),
        ('staff-west','private-gym-support-6',54.2,3.5,90),
        ('staff-front','private-gym-support-3',55.8,9.6,0),
    ]:place(key,aid,x,z,yaw,role='architecture',color='#d8e2df')
    place('reception-desk','desk-1400-clear-wood',7.5,2.4,90,role='amenity')
    place('reception-chair','chair-black',7.5,1.25,0,role='amenity')
    for i,(x,z) in enumerate(((8.6,6.2),(8.6,8.5))):
        place('lounge-table-'+str(i+1),'5589t51-round-plastic-folding-table',x,z,role='amenity')
        for j,dx in enumerate((-1.2,1.2)):
            place(f'lounge-chair-{i+1}-{j+1}','chair-black',x+dx,z,90 if dx<0 else 270,role='amenity')
    # A CAD sample remains distinct from the provisional floor finish. Its installed
    # repeat is measured separately; no unfounded full-floor procurement count.
    place('tile-sample','gym-commercial-inter-v4',52.8,8.9,role='floor-sample')
    def mark(key,b,color,text=''):
        x0,z0,x1,z1=b
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-private-gym-'+key,
            label=key.replace('-',' ').title(),markingType='floor_text' if text else 'solid_line',
            semanticRole='decorative',positionMode='manual',transform=dict(position=dict(x=(x0+x1)/2,y=.012 if text else .003,z=(z0+z1)/2),rotationDegrees=0),
            width=x1-x0,depth=z1-z0,fillColor=color,strokeColor=color,opacity=1,text=text,evidence=[],metadata=dict(authoredIn='private_gym'))))
    for key,label,b,color in ZONES:
        x0,z0,x1,z1=b
        mark(key+'-finish',(x0+.12,z0+.12,x1-.12,z1-.12), '#d8e0df' if key in ('reception','staff','support','circulation') else '#465257')
        mark(key+'-label',(x0+.8,z1-1.0,x1-.8,z1-.5),'#e7efef' if key not in ('staff','support','reception','circulation') else '#294955',label.upper())
    mark('mobility-mat',(37.8,5.8,46.8,9.2),'#397e7f')
    for key,points,width in ROUTES:
        ops.append(dict(op='add_aisle',routeId='rt-private-gym-'+key,aisle=dict(label=key.title()+' Walkway',
            centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,
            aisleKind='pedestrian',direction='two_way',color='#97b6ba',clearanceEvidenceStatus='unverified')))
    ops.append(dict(op='set_perimeter_walls',wallSettings=WALLS))
    result=apply_facility_layout_operations(blank,ops)['document']
    return result,ops


def audit(doc,catalog):
    scheduled=[p for p in doc['placements'] if p['metadata']['gymRole']=='schedule']
    expected=Counter({'asset-'+aid:len(positions) for _,aid,positions in EQUIPMENT})
    assert len(scheduled)==66 and Counter(p['assetId'] for p in scheduled)==expected
    assert not any('zoneId' in p for p in doc['placements'])
    shapes={p['placementId']:footprint(p,catalog[p['assetId']]) for p in doc['placements']}
    zones={key:box(*b) for key,_,b,_ in ZONES}
    membership={ 'asset-'+aid:area for area,aid,_ in EQUIPMENT }
    for p in scheduled:
        assert zones[membership[p['assetId']]].covers(shapes[p['placementId']]),p['placementId']
    overlaps=[]; blocked=[]
    for i,p in enumerate(doc['placements']):
        shape=shapes[p['placementId']]
        assert box(.09,.09,59.91,29.91).covers(shape), ('Outside room',p['placementId'])
        for other in doc['placements'][i+1:]:
            if shape.intersection(shapes[other['placementId']]).area>1e-7:
                overlaps.append([p['placementId'],other['placementId']])
        for key,points,width in ROUTES:
            if shape.intersection(LineString(points).buffer(width/2,cap_style=2,join_style=2)).area>1e-7:
                blocked.append([key,p['placementId']])
    assert not overlaps,overlaps
    assert not blocked,blocked
    pool=next(p for p in scheduled if 'pool-table' in p['assetId'])
    cue=shapes[pool['placementId']].buffer(1.4,join_style=2)
    assert zones['reception'].covers(cue)
    for p in doc['placements']:
        if p!=pool: assert cue.intersection(shapes[p['placementId']]).area<1e-7,('Cue allowance',p['placementId'])
    return dict(scheduledPlacements=66,totalPlacements=len(doc['placements']),zones=len(doc['zones']),
        geometricOverlaps=overlaps,blockedAuthoredWalkways=blocked,poolConceptCueAllowanceMeters=1.4,
        actualZoneAreas={k:v.area for k,v in zones.items()},operatingClearancesQualified=False)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=OUT)
    parser.add_argument('--open-sheet',action='store_true')
    args=parser.parse_args();out=args.output.resolve()
    before=saved_hashes();target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    assert not target.exists(),'Private Gym already exists; refusing to overwrite'
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    raw=manifest.read_bytes();library=json.loads(raw)
    out.mkdir(parents=True,exist_ok=True)
    (out/'catalog-before.json').write_bytes(raw)
    write(out/'saved-layout-hashes.json',before)
    artifacts=prepare_assets(out,library)
    source=json.loads((target.parent/'fl-independent-factory-20260928.json').read_text())
    blank=create_layout_document(layout_id=LAYOUT,display_name='Private Gym',association=source['association'],
        coordinate_frame=source['coordinateFrame'],source_shell_ref=source['sourceShellRef'],policy_set_ref=source['policySetRef'],
        created_at=datetime.now(timezone.utc).isoformat(),extensions={'extensions':{'facilityPlan':PLAN}})
    host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=out/'staged-project')
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        doc,ops=build(catalog,blank);checks=audit(doc,catalog)
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',doc)
        write(out/'spatial.json',spatial);host.service._require_spatially_valid(spatial)
        write(out/'candidate.json',doc);write(out/'operations.json',ops);write(out/'blank.json',blank)
        report=dict(status='validated',layoutId=LAYOUT,checks=checks,artifacts=artifacts,
            limitations=['Conceptual equipment access; manufacturer operating envelopes remain unqualified.',
                'Changing/toilet/staff areas reserved; fixtures and services not represented.',
                'Functional floor is a provisional finish with one CAD tile sample; broad tiling not installed.',
                'Loaded bars occupy dedicated floor bays; a compatible storage stand remains to be selected.'])
    finally:host.close()
    assert saved_hashes()==before,'An existing saved layout changed'
    assert manifest.read_bytes()==raw,'Catalog changed during preparation'
    if args.open_sheet:
        for artifact in artifacts:
            dest=ROOT/artifact;assert not dest.exists()
            dest.parent.mkdir(parents=True,exist_ok=True)
            RevisionedAuthorityRepository._atomic_write(dest,(out/'staged-project'/artifact).read_bytes())
        RevisionedAuthorityRepository._atomic_write(manifest,(out/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes())
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try: receipt=host.service.create_layout(host.principal(),'site-local',blank,make_default=False)
        finally:host.close()
        report.update(status='empty-sheet-created',baseRevision=receipt['revision'],equipmentSaved=False)
        current=saved_hashes()
        assert all(current[k]==v for k,v in before.items() if k!='registry.json')
        profile=dict(schemaVersion=1,mode='application',profileId='private-gym-review',origin='http://127.0.0.1:8536',
            dataRoot=str(out),facilityRoot=str(STORE),libraryRoot=str(ROOT/'400S_Sorted_Library'),
            startupLayoutId=LAYOUT,backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
        write(out/'profile.json',profile)
    write(out/'report.json',report)
    print(json.dumps(report))


if __name__=='__main__':main()
