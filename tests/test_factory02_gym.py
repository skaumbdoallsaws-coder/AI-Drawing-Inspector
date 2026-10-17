from copy import deepcopy
import json
from pathlib import Path
import pytest
from shapely.geometry import box
from shapely.ops import unary_union
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.plan_settings import shell_with_plan_boundary
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools import add_factory02_gym as gym
from tools.audit_independent_factory_layer2 import marking_polygon


def build():
    before=json.loads((Path(__file__).parent/'fixtures/facility_layout/empty_cell.json').read_text())
    before.update(floorMarkings=[],extensions=dict(facilityPlan=dict(widthMeters=376,depthMeters=200,
        gridSpacingMeters=1.524,majorGridSpacingMeters=7.62)))
    sizes={'multi-station':(2.195,1.431,2.148),'bench-press':(2.001,1.325,1.068),
        'flat-bench':(.73,1.312,1.068),'weight-rack':(1.535,2,2.117),
        'vertical-leg-press':(3,3,2.183),'x1000':(1.842,1.564,2.236),
        'dumbbell-rack':(1.471,1.241,2.181),'multi-gym-stl':(1.99,3.362,3.111)}
    sizes={'asset-gym-'+key:value for key,value in sizes.items()}
    sizes.update({'asset-factory02-gym-wall-'+key:(x1-x0,z1-z0,gym.HEIGHT)
        for key,(x0,z0,x1,z1),_ in gym.WALLS})
    catalog={}
    for aid,(w,d,h) in sizes.items():
        g=dict(footprintPolygons=[gym.boundary((-w/2,-d/2,w/2,d/2))],heightInterval=dict(minimumY=0,maximumY=h))
        catalog[aid]=dict(assetId=aid,assetDefinitionRevision='a'*64,definition=dict(geometry=g),geometry=g,clearances=[])
    snapshot=deepcopy(before)
    result=apply_facility_layout_operations(before,gym.operations(catalog))['document']
    assert before==snapshot
    return before,result,catalog


def test_complete_equipment_and_clear_concept_spacing():
    before,result,catalog=build()
    report=gym.audit(before,result,catalog)
    assert report['gymEquipment']==13 and report['roomAreaM2']==468
    assert report['sourceModelTypes']==8 and report['brandedWalls']==2
    assert all('zoneId' not in p for p in result['placements'])


def test_real_validator_accepts_room_and_rejects_blocked_door():
    _,result,catalog=build()
    def metrics(layout):
        return diagnose_layout(layout,list(catalog.values()),shell=shell_with_plan_boundary({'features':[]},layout))['metrics']
    m=metrics(result)
    assert m['placementCollisions']==0 and m['obstructedAisleCount']==0
    blocked=deepcopy(result)
    wall=next(p for p in blocked['placements'] if p['placementId']=='pl-gym-wall-east-left')
    wall['transform']['position']['z']=84
    assert metrics(blocked)['obstructedAisleCount']>0


@pytest.mark.parametrize('fault',['unrelated-change','missing-equipment','blocked-walkway','overlap'])
def test_audit_rejects_invalid_candidate(fault):
    before,result,catalog=build()
    if fault=='unrelated-change':result['displayName']='Unexpected rename'
    elif fault=='missing-equipment':result['placements'].pop()
    else:
        p=next(p for p in result['placements'] if p['placementId']=='pl-gym-dumbbell-rack-01')
        p['transform']['position']=dict(x=310.3 if fault=='blocked-walkway' else 314.4,y=0,z=84 if fault=='blocked-walkway' else 87.8)
    with pytest.raises(AssertionError):gym.audit(before,result,catalog)


def test_floor_and_six_mats_do_not_overlap_walkway():
    _,result,_=build()
    markings=[m for m in result['floorMarkings'] if m['markingType']!='floor_text']
    assert sum(m['markingId'].startswith('fm-gym-stretch-mat-') for m in markings)==6
    shapes=[marking_polygon(m) for m in markings]
    for i,p in enumerate(shapes):assert all(p.intersection(q).area<1e-8 for q in shapes[i+1:])
    expected=box(302.2,76.2,327.8,93.8).difference(box(303.5,83,327.8,85))
    assert unary_union(shapes).symmetric_difference(expected).area<1e-8
