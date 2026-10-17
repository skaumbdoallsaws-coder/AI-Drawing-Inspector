from copy import deepcopy
import pytest
from ai_inspector.facility_layout.host import _asset
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools.add_private_gym_fitness_centre import A, P, PAD, REMOVED, operations, footprint, yaw


def fixture():
    before=dict(placements=[dict(placementId=pid) for pid in REMOVED],floorMarkings=[dict(markingId=PAD)])
    catalog={}
    for kind,width,depth,height in [('centre',5.698,7.193,3.121),('wagon',4.06,1.604,2.596)]:
        a=_asset(asset_id=A+kind,display_name=kind,category='Gym Equipment',
            width=width,depth=depth,height=height,description='')
        catalog[a['assetId']]=a
    return before,catalog


def test_only_requested_equipment_is_replaced_without_mutating_inputs():
    before,catalog=fixture()
    original=deepcopy(before)
    ops=operations(before,catalog)
    assert before==original
    assert {o['placementId'] for o in ops if o['op']=='delete_placement'}==REMOVED
    assert sum(o['op']=='place_asset' for o in ops)==2
    assert len(ops)==6
    assert ops[3]['markingId']==PAD


def test_new_assets_are_revision_bound_and_unscaled():
    before,catalog=fixture()
    placements=[o['placement'] for o in operations(before,catalog) if o['op']=='place_asset']
    assert {p['placementId'] for p in placements}=={P+k for k in ['centre','wagon']}
    for p in placements:
        assert p['assetDefinitionRevision']==catalog[p['assetId']]['assetDefinitionRevision']
        assert p['transform']['scale']==1
        assert p['transform']['position']['y']==0


def test_centre_fits_existing_pad_and_leaves_front_approach_free():
    before,catalog=fixture()
    p={o['placement']['assetId']:o['placement'] for o in operations(before,catalog) if o['op']=='place_asset'}
    a=footprint(p[A+'centre'],catalog)
    assert 55<a[0]<a[2]<67 and 63.55<a[1]<a[3]<71.05
    assert a[1]-63.55>1.5
    assert A+'weights' not in p
    assert p[A+'centre']['transform']['quaternion']==yaw(90)


def test_wagon_is_lengthwise_in_decorative_strip():
    before,catalog=fixture()
    p=next(o['placement'] for o in operations(before,catalog) if o.get('placement',{}).get('assetId')==A+'wagon')
    x0,z0,x1,z1=footprint(p,catalog)
    assert x1-x0==pytest.approx(1.604)
    assert z1-z0==pytest.approx(4.06)
    assert 75<x0<x1<81 and 53<z0<z1<61
    assert 62-z1>1.5


@pytest.mark.parametrize('missing',['equipment','pad','catalog'])
def test_missing_input_stops_before_a_partial_plan(missing):
    before,catalog=fixture()
    if missing=='equipment':before['placements'].pop()
    elif missing=='pad':before['floorMarkings'].clear()
    else:del catalog[A+'centre']
    with pytest.raises((AssertionError,KeyError)):
        operations(before,catalog)


def test_new_equipment_is_grounded_and_non_overlapping():
    before,catalog=fixture()
    layout=dict(placements=[o['placement'] for o in operations(before,catalog) if o['op']=='place_asset'],
        zones=[],routes=[],floorMarkings=[])
    shell=dict(features=[dict(featureId='floor',featureKind='floor_surface',geometry=dict(elevation=0,
        boundary=[dict(x=x,z=z) for x,z in [(44,40),(82,40),(82,72),(44,72)]]))])
    findings=diagnose_layout(layout,list(catalog.values()),shell=shell)['findings']
    assert not [f for f in findings if f['severity']=='error']
