from copy import deepcopy
import json
import hashlib
import math
from pathlib import Path
import pytest
from shapely.geometry import LineString
from tools.audit_independent_factory_layer2 import marking_polygon
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.plan_settings import shell_with_plan_boundary
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools import add_factory02_parking_office as annex


def inputs(monkeypatch):
    doc = json.loads((Path(__file__).parent/'fixtures/facility_layout/empty_cell.json').read_text())
    doc.update(layoutId=annex.LAYOUT_ID, zones=[], routes=[], floorMarkings=[])
    doc.setdefault('extensions', {})['facilityPlan'] = dict(widthMeters=300.01464,
        depthMeters=200.04024, gridSpacingMeters=1.524, majorGridSpacingMeters=7.62)
    doc['placements'] = [dict(placementId=annex.REPLACED_WALL, assetId='asset-existing-wall',
        assetDefinitionRevision='a'*64, positionMode='locked', snapRelationship=None, metadata={},
        transform=dict(position=dict(x=299.88964,y=0,z=45.63),
                       quaternion=dict(x=0,y=0,z=0,w=1),scale=1))]
    sizes = {
        annex.CAR_IDS[0]: (1.84697485,4.721244335,1.395561213),
        annex.CAR_IDS[1]: (2.044932842,4.76256576,1.284202329),
        annex.CUBICLE: (2.163736445,2.163736496,1.676399946),
        annex.CHAIR: (.587000012,.549902223,.829925656),
        'asset-existing-wall': (.25,90.74,6),
    }
    sizes.update({a['assetId']:tuple(a['dimensions'][k] for k in ('width','depth','height'))
                  for a in annex.primitives()[1]})
    catalog = {}
    for aid,(w,d,h) in sizes.items():
        catalog[aid] = dict(assetId=aid,assetDefinitionRevision='a'*64,displayName=aid,
            definition=dict(readiness=dict(placementReady=dict(value=True))),
            geometry=dict(footprintPolygons=[annex.boundary((-w/2,-d/2,w/2,d/2))],
                          heightInterval=dict(minimumY=0,maximumY=h)),clearances=[])
        catalog[aid]['definition']['geometry']=deepcopy(catalog[aid]['geometry'])
    monkeypatch.setattr(annex,'layout_revision',lambda _:annex.BASE)
    return doc,catalog


def build(monkeypatch):
    doc,catalog=inputs(monkeypatch)
    ops,stalls=annex.operations(doc,catalog)
    result=apply_facility_layout_operations(doc,ops)['document']
    return doc,catalog,ops,stalls,result


def test_real_kernel_counts_fit_and_unrelated_content_preservation(monkeypatch):
    doc,catalog,ops,stalls,result=build(monkeypatch)
    assert annex.audit(doc,result,catalog,stalls)['addedPlacements']==68
    assert len({p['placementId'] for p in result['placements']})==68
    assert {p['assetId'] for p in result['placements'] if '-car-' in p['placementId']}==set(annex.CAR_IDS)
    assert len(stalls)==20 and sum(s['accessible'] for s in stalls)==2
    assert len(result['routes'])==3
    assert all('zoneId' not in p for p in result['placements'])
    assert annex.operations(doc,catalog)==(ops,stalls)


def test_input_unchanged_and_only_one_existing_wall_replaced(monkeypatch):
    doc,catalog=inputs(monkeypatch)
    before=deepcopy((doc,catalog))
    ops,_=annex.operations(doc,catalog)
    assert (doc,catalog)==before
    assert [o for o in ops if o['op']=='delete_placement']==[
        dict(op='delete_placement',placementId=annex.REPLACED_WALL)]
    assert not any(o['op'] in {'move_placement','set_perimeter_walls'} for o in ops)


def test_chairs_face_their_cubicles(monkeypatch):
    *_,result=build(monkeypatch)
    by_id={p['placementId']:p for p in result['placements']}
    for p in result['placements']:
        if p['assetId']!=annex.CHAIR:
            continue
        desk=by_id[p['placementId'].replace('chair-','cubicle-')]['transform']['position']
        pos,q=p['transform']['position'],p['transform']['quaternion']
        dx,dz=desk['x']-pos['x'],desk['z']-pos['z']
        length=math.hypot(dx,dz)
        assert 2*q['y']*q['w']==pytest.approx(dx/length)
        assert 1-2*q['y']**2==pytest.approx(dz/length)


def test_ground_tiles_do_not_overlap_each_other_or_pedestrian_route_paint(monkeypatch):
    *_,result=build(monkeypatch)
    floors=[marking_polygon(m) for m in result['floorMarkings']
            if m['markingId'].startswith(('fm-parking-office-000-','fm-parking-office-001-'))]
    corridors=[]
    for route in result['routes']:
        points=route['centerline']
        for a,b in zip(points,points[1:]):
            corridors.append(LineString([(a['x'],a['z']),(b['x'],b['z'])]).buffer(
                route['corridorWidth']/2,cap_style=2))
    for i,floor in enumerate(floors):
        assert all(floor.intersection(other).area<1e-8 for other in floors[i+1:]+corridors)


def test_real_spatial_validator_detects_closed_office_entrance(monkeypatch):
    _,catalog,_,_,result=build(monkeypatch)
    def metrics(layout):
        return diagnose_layout(layout,list(catalog.values()),
            shell=shell_with_plan_boundary({'features':[]},layout))['metrics']
    assert metrics(result)['obstructedAisleCount']==0
    bad=deepcopy(result)
    wall=next(p for p in bad['placements'] if p['placementId'].endswith('wall-office-west-lower'))
    wall['transform']['position']['z']=19
    assert metrics(bad)['obstructedAisleCount']>0


@pytest.mark.parametrize('failure',['scale','wrong-car','outside-bay','move-existing'])
def test_audit_rejects_wrong_scale_models_fit_or_unrelated_changes(monkeypatch,failure):
    doc,catalog,_,stalls,result=build(monkeypatch)
    car=next(p for p in result['placements'] if p['placementId'].endswith('car-01'))
    if failure=='scale':car['transform']['scale']=.25
    elif failure=='wrong-car':car['assetId']='asset-import-car-concept'
    elif failure=='outside-bay':car['transform']['position']['x']+=2
    else:result['name']='Unrelated rename'
    with pytest.raises(AssertionError):annex.audit(doc,result,catalog,stalls)


def test_wrong_layout_stale_revision_and_unready_cubicle_refuse(monkeypatch):
    doc,catalog=inputs(monkeypatch)
    with pytest.raises(ValueError,match='changed'):annex.operations(dict(doc,layoutId='fl-other'),catalog)
    catalog[annex.CUBICLE]['definition']['readiness']['placementReady']['value']=False
    with pytest.raises(ValueError,match='not placement-ready'):annex.operations(doc,catalog)
    monkeypatch.setattr(annex,'layout_revision',lambda _:'stale')
    with pytest.raises(ValueError,match='changed'):annex.operations(doc,catalog)


def test_native_guard_binds_reviewed_store_bytes_to_candidate_semantics():
    candidate={'layoutId':annex.LAYOUT_ID,'value':1}
    stored=json.dumps(candidate,indent=2).encode()+b'\n'
    native={'status':'passed','candidateHash':hashlib.sha256(stored).hexdigest()}
    annex.verify_native_candidate(native,json.loads(json.dumps(candidate)),stored)
    with pytest.raises(AssertionError,match='store bytes changed'):
        annex.verify_native_candidate(native,candidate,stored+b' ')
    with pytest.raises(AssertionError,match='differs from reviewed'):
        annex.verify_native_candidate(native,dict(candidate,value=2),stored)
    with pytest.raises(AssertionError,match='acceptance required'):
        annex.verify_native_candidate(dict(native,status='failed'),candidate,stored)
