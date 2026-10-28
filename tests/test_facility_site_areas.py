import copy
import pytest
from tests.test_facility_site_property import fixture
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.site_context import KEY, analyze_site_context, normalize_site_context
from ai_inspector.facility_layout.errors import FacilityLayoutError

def area(identity, x, z, width, depth, kind='parking'):
    return {'areaId':identity,'label':identity,'kind':kind,'boundary':[
        {'x':x,'z':z},{'x':x+width,'z':z},{'x':x+width,'z':z+depth},{'x':x,'z':z+depth}]}

def doc_with(*areas):
    doc=fixture();doc['extensions'][KEY]['property']['setbacksMeters']={'street':0,'side':0,'rear':0}
    doc['extensions'][KEY]['areas']=list(areas)
    return doc

def test_adjacent_outdoor_areas_share_edges_without_overlap_and_union_metrics_are_exact():
    doc=doc_with(area('parking',60,10,20,20),area('drive',80,10,10,20,'drive'),area('lawn',60,30,30,10,'landscape'))
    a=analyze_site_context(doc)
    assert not a['findings']
    assert a['metrics']['pavedAreaSquareMeters']==600
    assert len(a['metrics']['areas'])==3

def test_outside_building_overlap_and_area_overlap_are_reported_separately():
    doc=doc_with(area('a',5,5,20,20),area('b',10,10,20,20),area('c',95,60,20,20))
    codes={f['code'] for f in analyze_site_context(doc)['findings']}
    assert {'site_area_outside_property','site_area_overlap','site_area_overlaps_building'} <= codes

def test_area_setbacks_name_the_edge_and_paving_is_not_double_counted():
    doc=doc_with(area('a',60,0,20,20),area('b',70,0,20,20))
    doc['extensions'][KEY]['property']['setbacksMeters']['street']=5
    a=analyze_site_context(doc)
    assert a['metrics']['pavedAreaSquareMeters']==600
    assert any(f['code']=='site_area_setback_violation' and f['edgeIndex']==0 for f in a['findings'])

def gated(*areas, edge=0, x=70, z=0, use='trucks'):
    doc=doc_with(*areas);prop=doc['extensions'][KEY]['property']
    prop['setbacksMeters']['street']=5
    prop['entrances']=[{'entranceId':'truck-gate','edgeIndex':edge,'x':x,'z':z,'use':use,'widthMeters':12}]
    return doc

def test_a_drive_may_cross_the_street_setback_through_its_entrance():
    a=analyze_site_context(gated(area('drive',64,0,12,20,'drive')))
    assert not a['findings']
    assert a['metrics']['entranceCrossings']==[{'areaId':'drive','edgeIndex':0,'entranceIds':['truck-gate']}]

@pytest.mark.parametrize('case,message',[
    ('wider','beyond the entrance width.'),('parking','setback is not met.'),
    ('pedestrian gate','setback is not met.'),('gate on another edge','setback is not met.')])
def test_only_access_areas_inside_a_usable_entrance_may_cross(case,message):
    drive=area('drive',64,0,12,20,'drive')
    doc={'wider':lambda:gated(area('drive',63,0,14,20,'drive')),
         'parking':lambda:gated(area('drive',64,0,12,20,'parking')),
         'pedestrian gate':lambda:gated(drive,use='pedestrians'),
         'gate on another edge':lambda:gated(drive,edge=2,z=80)}[case]()
    a=analyze_site_context(doc)
    found=[f for f in a['findings'] if f['code']=='site_area_setback_violation']
    assert len(found)==1 and found[0]['edgeIndex']==0 and found[0]['message'].endswith(message)
    assert a['metrics']['entranceCrossings']==[]

def test_area_operations_reuse_ids_preserve_interior_and_delete_exactly_one():
    doc=doc_with();before=copy.deepcopy(doc)
    first=apply_facility_layout_operations(doc,[{'op':'upsert_site_area','area':area('parking',60,10,20,20)}])['document']
    updated=apply_facility_layout_operations(first,[{'op':'upsert_site_area','area':area('parking',60,10,25,20)}])['document']
    assert len(updated['extensions'][KEY]['areas'])==1
    assert updated['placements']==doc['placements'] and doc==before
    removed=apply_facility_layout_operations(updated,[{'op':'delete_site_area','areaId':'parking'}])['document']
    assert removed['extensions'][KEY]['areas']==[]
    with pytest.raises(FacilityLayoutError):
        apply_facility_layout_operations(removed,[{'op':'delete_site_area','areaId':'missing'}])

@pytest.mark.parametrize('patch',[{'kind':'road-network'},{'surface':'unknown'},{'areaId':''},{'label':''}, {'extra':1}])
def test_invalid_areas_are_rejected(patch):
    doc=doc_with({**area('a',60,10,20,20),**patch})
    with pytest.raises(ValueError):normalize_site_context(doc['extensions'][KEY],doc)
