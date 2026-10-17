"""Prepare Private Gym's second pass; publishing assets never saves a layout."""
from copy import deepcopy
import argparse
import hashlib
import json
import math
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import trimesh
from shapely.affinity import translate
from shapely import set_precision
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools import build_private_gym as gym
from tools.audit_independent_factory_layer2 import footprint, marking_polygon
from tools.expand_factory02_lunchroom import rectangle_tiles

OUT = ROOT / '.runtime/private-gym-detail-20261007'
MAT = 'asset-private-gym-mat-20x7'
PITCH = .46
MAT_POSITION = (42.3, 7.55)
ROUTES = gym.ROUTES + [
    ('changing', [(45.8,23),(57,23),(57,25)],1.2),
    ('wash', [(45.8,23),(50.1,23),(50.1,21),(56,21)],1.2),
    ('staff', [(58.2,11),(58.2,8),(56,8),(56,4.5)],1.2),
    ('cardio-access', [(11.2,11),(11.2,7.4),(34.8,7.4),(34.8,1)],1.2),
]


def mat_mesh(source):
    mesh = trimesh.load(source, force='scene').to_mesh()
    top = mesh.triangles[np.all(np.abs(mesh.triangles[:,:,1]-.02)<1e-6,axis=1)]
    outline = set_precision(unary_union([Polygon(face[:,[0,2]]) for face in top]),1e-7)
    small = [set_precision(translate(outline,xoff=x*PITCH,yoff=z*PITCH),1e-7)
             for x in range(2) for z in range(2)]
    union = unary_union(small)
    assert union.geom_type=='Polygon' and not union.interiors
    assert abs(sum(p.area for p in small)-union.area)<1e-7
    pieces=[]
    for x in range(20):
        for z in range(7):
            tile=mesh.copy()
            tile.apply_translation(((x-9.5)*PITCH,0,(z-3)*PITCH))
            pieces.append(tile)
    joined=trimesh.util.concatenate(pieces)
    assert len(joined.faces)==140*len(mesh.faces)
    return joined,dict(tileCount=140,pitchMeters=PITCH,nominalCoverageM2=140*outline.area,
                      smallPatchConnected=True,smallPatchOverlapM2=sum(p.area for p in small)-union.area,
                      sourceGeometryUnscaled=True,triangles=len(joined.faces))


def detail(before,catalog):
    ops=[]
    # The previously reviewed exercise schedule stays intact, including all IDs.
    for p in before['placements']:
        label=p['metadata'].get('instanceLabel','')
        if label in ('Support West A','Support West B'):
            pos=deepcopy(p['transform']['position'])
            pos['z']=16.3 if label.endswith('A') else 26.8
            ops.append(dict(op='move_placement',placementId=p['placementId'],movementKind='user',position=pos))
    def place(key,aid,x,z,yaw=0,role='support-furniture',color=None):
        q=math.radians(yaw)/2
        p=dict(placementId='pl-private-gym-detail-'+key,assetId=aid,
            assetDefinitionRevision=catalog[aid]['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=0,z=z),quaternion=dict(x=0,y=math.sin(q),z=0,w=math.cos(q)),scale=1),
            positionMode='manual',snapRelationship=None,
            metadata=dict(instanceLabel=key.replace('-',' ').title(),gymRole=role,inputMethod='independent-authoring'))
        if color:p['appearance']=dict(color=color)
        ops.append(dict(op='place_asset',placement=p))
    place('mobility-tile-mat',MAT,*MAT_POSITION,role='floor-mat',color='#397e7f')
    for i,x in enumerate((54,57),1):
        place('changing-bench-'+str(i),'asset-public-contemporary-bench',x,26.3)
        place('towel-cabinet-'+str(i),'asset-hideaway-cabinet',x,29,180)
        place('wash-sink-'+str(i),'asset-user-library-sink-1',x,13.2)
    place('wash-bench','asset-public-contemporary-bench',54,16)
    place('staff-desk','asset-desk-1400-clear-wood',56,2.5,90)
    place('staff-chair','asset-chair-black',56,1.25)
    place('staff-storage','asset-hideaway-cabinet',58.7,3,270)
    place('staff-drawers','asset-user-library-drawers-4-6in-x-42in-w',58.7,5.5,270)
    # Finish rectangles exclude paths and the physical mat, rather than fighting
    # overlapping transparent paint at nearly the same depth.
    for m in before['floorMarkings']:
        ops.append(dict(op='delete_floor_marking',markingId=m['markingId']))
    for r in before['routes']:
        ops.append(dict(op='delete_route',routeId=r['routeId']))
    corridors=[LineString([a,b]).buffer(width/2,cap_style=2,join_style=2)
               for _,points,width in ROUTES for a,b in zip(points,points[1:])]
    corridors += [box(x-width/2,z-width/2,x+width/2,z+width/2)
                  for _,points,width in ROUTES for x,z in points[1:-1]]
    mat_bounds=box(42.3-4.62,7.55-1.63,42.3+4.62,7.55+1.63)
    def paint(key,b,color,text=''):
        x0,z0,x1,z1=b
        ops.append(dict(op='add_floor_marking',floorMarking=dict(markingId='fm-private-gym-detail-'+key,
            label=key.replace('-',' ').title(),markingType='floor_text' if text else 'solid_line',
            semanticRole='decorative',positionMode='manual',
            transform=dict(position=dict(x=(x0+x1)/2,y=.018 if text else 0,z=(z0+z1)/2),rotationDegrees=0),
            width=x1-x0,depth=z1-z0,fillColor=color,strokeColor=color,opacity=1,text=text,evidence=[],
            metadata=dict(authoredIn='private_gym_detail'))))
    for key,label,b,color in gym.ZONES:
        x0,z0,x1,z1=b
        for index,tile in enumerate(rectangle_tiles((x0+.12,z0+.12,x1-.12,z1-.12),corridors+[mat_bounds])):
            paint(key+'-finish-'+str(index),tile,'#d8e0df' if key in ('reception','staff','support','circulation') else '#465257')
        if key not in ('circulation','support','staff'):
            paint(key+'-label',(x0+.8,z1-1,x1-.8,z1-.5),'#b8cdcf' if key!='reception' else '#294955',label.upper())
    paint('changing-label',(52,27.7,59,28.2),'#294955','CHANGING + TOWEL STORAGE')
    paint('wash-label',(52,18,59,18.5),'#294955','WASH AREA / FIXTURES RESERVED')
    paint('staff-label',(55,7,59,7.4),'#294955','STAFF + STORAGE')
    for key,points,width in ROUTES:
        ops.append(dict(op='add_aisle',routeId='rt-private-gym-'+key,aisle=dict(label=key.title()+' Walkway',
            centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,
            aisleKind='pedestrian',direction='two_way',color='#97b6ba',clearanceEvidenceStatus='unverified')))
    return apply_facility_layout_operations(before,ops)['document'],ops


def audit(before,after,catalog):
    prior={p['placementId']:p for p in before['placements'] if p['metadata']['gymRole']=='schedule'}
    assert {p['placementId']:p for p in after['placements'] if p['placementId'] in prior}==prior
    shapes={p['placementId']:footprint(p,catalog[p['assetId']]) for p in after['placements']}
    route_shape=unary_union([LineString(points).buffer(w/2,cap_style=2,join_style=2) for _,points,w in ROUTES])
    assert route_shape.geom_type=='Polygon'
    assert box(0,0,60,30).covers(route_shape)
    for i,p in enumerate(after['placements']):
        shape=shapes[p['placementId']]
        assert box(.09,.09,59.91,29.91).covers(shape),('outside',p['placementId'])
        assert shape.intersection(route_shape).area<1e-7,('blocked',p['placementId'])
        for q in after['placements'][i+1:]:
            assert shape.intersection(shapes[q['placementId']]).area<1e-7,('overlap',p['placementId'],q['placementId'])
    finishes=[marking_polygon(m) for m in after['floorMarkings'] if m['markingType']=='solid_line']
    assert abs(sum(p.area for p in finishes)-unary_union(finishes).area)<1e-7
    assert all(p.intersection(route_shape).area<1e-7 for p in finishes)
    clearances=[]
    for p in after['placements']:
        if p['placementId'] not in prior:continue
        nearest=min((shapes[p['placementId']].distance(s),pid) for pid,s in shapes.items() if pid!=p['placementId'])
        clearances.append(dict(placementId=p['placementId'],nearestPlacementId=nearest[1],
                               nearestFootprintGapMeters=nearest[0],operatingEnvelopeVerified=False))
    return dict(placements=len(after['placements']),scheduledPlacementsPreserved=len(prior),
        routes=len(ROUTES),routeNetworkConnected=True,footprintOverlaps=0,blockedRoutes=0,
        finishIntersections=0,machineGapAudit=clearances,
        limitations=['Footprint gaps are not manufacturer operating clearances.',
            'Toilets, showers and lockers are not supplied by the present library.',
            'Mat is 29.624 m2, not the initial 120 m2 flooring proposal; edge trim and transition remain unqualified.',
            'Loaded-bar storage and two generic station exercise identities remain unresolved.'])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-assets',action='store_true')
    args=parser.parse_args()
    OUT.mkdir(parents=True,exist_ok=True)
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    raw=manifest.read_bytes();library=json.loads(raw)
    initial_hashes=gym.saved_hashes()
    tile=next(a for a in library['assets'] if a['assetId']=='asset-gym-commercial-inter-v4')
    mesh,mat_report=mat_mesh(ROOT/tile['artifact'])
    artifact='generated/industrial_assets/private_gym/mobility-mat/model.glb'
    payload=mesh.export(file_type='glb')
    d=mesh.bounds[1]-mesh.bounds[0]
    spec=dict(assetId=MAT,displayName='Gym Mobility Mat - 140 Interlocking CAD Tiles',category='Facilities',
        dimensions=dict(width=float(d[0]),height=float(d[1]),depth=float(d[2])),artifact=artifact,
        sourceToCanonical=gym.IDENTITY,tags=['gym','mat','floor'],
        description='Unscaled user CAD tiles at measured 460 mm pitch; edge treatment and slip resistance unverified.',
        source=dict(kind='derived-cad-array',sourceAssetId=tile['assetId'],sourceSha256=hashlib.sha256((ROOT/tile['artifact']).read_bytes()).hexdigest(),
                    columns=20,rows=7,pitchMeters=PITCH))
    existing=next((a for a in library['assets'] if a['assetId']==MAT),None)
    if existing:assert existing==spec
    else:library['assets'].append(spec)
    library['summary']['total']=len(library['assets'])
    stage=OUT/'staged-project'
    dest=stage/artifact;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload)
    gym.write(stage/PRIVATE_ASSET_MANIFEST,library)
    host=LocalFacilityLayoutHost(OUT/'validation-store',private_assets=True,private_asset_root=stage)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        blank=json.loads((gym.OUT/'blank.json').read_text())
        first,_=gym.build(catalog,blank)
        candidate,ops=detail(first,catalog)
        checks=audit(first,candidate,catalog)
        # This diagnostic host uses the existing source authority for the blank.
    finally:host.close()
    host=LocalFacilityLayoutHost(gym.STORE,private_assets=True,private_asset_root=stage)
    try:
        spatial=host.service._diagnose_spatial(host.principal(),'site-local',candidate)
        host.service._require_spatially_valid(spatial)
    finally:host.close()
    gym.write(OUT/'candidate.json',candidate)
    # Desktop authoring consumes the final document and creates these paint/routes.
    final_ops=[dict(op='add_floor_marking',floorMarking=m) for m in candidate['floorMarkings']]
    for key,points,width in ROUTES:
        final_ops.append(dict(op='add_aisle',aisle=dict(label=key.title()+' Walkway',
            centerline=[dict(x=x,y=0,z=z) for x,z in points],corridorWidth=width,
            aisleKind='pedestrian',direction='two_way',color='#97b6ba',clearanceEvidenceStatus='unverified')))
    final_ops.append(dict(op='set_perimeter_walls',wallSettings=gym.WALLS))
    gym.write(OUT/'operations.json',final_ops);gym.write(OUT/'detail-operations.json',ops)
    gym.write(OUT/'spatial.json',spatial);gym.write(OUT/'saved-layout-hashes.json',initial_hashes)
    gym.write(OUT/'report.json',dict(status='validated',checks=checks,mat=mat_report))
    assert gym.saved_hashes()==initial_hashes
    assert manifest.read_bytes()==raw
    if args.publish_assets and not existing:
        live=ROOT/artifact;assert not live.exists()
        live.parent.mkdir(parents=True,exist_ok=True)
        RevisionedAuthorityRepository._atomic_write(live,payload)
        RevisionedAuthorityRepository._atomic_write(manifest,(stage/PRIVATE_ASSET_MANIFEST).read_bytes())
    profile=json.loads((gym.OUT/'profile.json').read_text())
    profile.update(profileId='private-gym-detail-review',origin='http://127.0.0.1:8537',dataRoot=str(OUT),
                   backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    gym.write(OUT/'profile.json',profile)
    print(json.dumps(dict(status='validated',placements=len(candidate['placements']),routes=len(ROUTES),mat=mat_report)))


if __name__=='__main__':main()
