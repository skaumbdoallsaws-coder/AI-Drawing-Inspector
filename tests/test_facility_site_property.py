import copy
import json
from pathlib import Path
import pytest
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.site_context import KEY, normalize_site_context, analyze_site_context
from ai_inspector.facility_layout.validate import validate_layout

def fixture():
    doc = json.loads((Path(__file__).parent / 'fixtures/facility_layout/empty_cell.json').read_text())
    doc.setdefault('extensions', {})[KEY] = {
        'version': 1, 'georeference': {'originLatitude': 45, 'originLongitude': -93},
        'buildingPose': {'x': 10, 'z': 10, 'bearingDegrees': 0},
        'property': {'boundary': [{'x': 0, 'z': 0}, {'x': 100, 'z': 0}, {'x': 100, 'z': 80}, {'x': 0, 'z': 80}],
                     'streetEdges': [0], 'rearEdges': [2], 'setbacksMeters': {'street': 12, 'side': 5, 'rear': 9}}}
    return doc

def test_property_metrics_setback_names_edge_and_preserves_order():
    doc = fixture()
    context = normalize_site_context(doc['extensions'][KEY], doc)
    assert context['property']['boundary'] == doc['extensions'][KEY]['property']['boundary']
    analysis = analyze_site_context(doc)
    assert analysis['metrics']['lotAreaSquareMeters'] == 8000
    assert analysis['metrics']['lotAreaAcres'] == pytest.approx(1.976843052)
    assert analysis['metrics']['buildingInsideProperty']
    findings = analysis['findings']
    assert len(findings) == 1 and findings[0]['code'] == 'site_setback_violation'
    assert findings[0]['edgeIndex'] == 0 and 'Edge 1' in findings[0]['message']

def test_pose_operation_leaves_interior_and_property_unchanged_and_roundtrips():
    doc = fixture(); before = copy.deepcopy(doc)
    edited = apply_facility_layout_operations(doc, [{'op': 'set_building_pose',
        'buildingPose': {'x': 45, 'z': 15, 'bearingDegrees': 37}}])['document']
    assert doc == before
    for key in ('placements', 'zones', 'routes'):
        assert edited.get(key) == doc.get(key)
    assert edited['extensions'][KEY]['property']['boundary'] == doc['extensions'][KEY]['property']['boundary']
    reopened = json.loads(json.dumps(edited)); validate_layout(reopened)
    assert analyze_site_context(reopened) == analyze_site_context(edited)
    restored = apply_facility_layout_operations(edited, [{'op': 'set_building_pose',
        'buildingPose': doc['extensions'][KEY]['buildingPose']}])['document']
    assert analyze_site_context(restored) == analyze_site_context(doc)

def test_concave_boundary_rejects_building_crossing_the_notch():
    doc = fixture()
    doc['extensions'][KEY]['property'] = {'boundary': [
        {'x': 0, 'z': 0}, {'x': 100, 'z': 0}, {'x': 100, 'z': 80},
        {'x': 25, 'z': 80}, {'x': 25, 'z': 20}, {'x': 0, 'z': 20}]}
    assert any(f['code'] == 'site_building_outside_property' for f in analyze_site_context(doc)['findings'])

@pytest.mark.parametrize('patch', [
    {'boundary': [{'x': 0, 'z': 0}, {'x': 10, 'z': 10}, {'x': 0, 'z': 10}, {'x': 10, 'z': 0}]},
    {'streetEdges': [True]}, {'streetEdges': [4]}, {'rearEdges': [0]},
    {'setbacksMeters': {'side': -1}}, {'setbacksMeters': {'side': float('nan')}},
    {'entrances': [{'entranceId': 'gate', 'x': 50, 'z': 20, 'edgeIndex': 0}]},
    {'entrances': [{'entranceId': 'gate', 'x': 1, 'z': 0, 'edgeIndex': 0, 'widthMeters': 10}]},
])
def test_invalid_property_input_is_rejected(patch):
    doc = fixture(); context = doc['extensions'][KEY]
    context['property'].update(patch)
    with pytest.raises(ValueError): normalize_site_context(context, doc)

def test_clockwise_edges_keep_their_identity_and_valid_entrances_survive():
    doc = fixture(); context = doc['extensions'][KEY]
    prop = context['property']; prop['boundary'].reverse()
    prop['entrances'] = [{'entranceId': 'truck-gate', 'edgeIndex': 0, 'x': 50, 'z': 80, 'use': 'trucks', 'widthMeters': 12}]
    assert normalize_site_context(context, doc)['property']['entrances'] == prop['entrances']
    assert analyze_site_context(doc)['metrics']['edges'][0]['kind'] == 'street'

def test_no_site_and_no_property_are_distinct():
    doc = fixture(); doc['extensions'][KEY].pop('property')
    assert analyze_site_context(doc)['findings'][0]['code'] == 'site_property_missing'
    doc['extensions'].pop(KEY)
    assert analyze_site_context(doc)['available'] is False

def test_analysis_endpoint_is_read_only_scoped_and_checks_draft_identity(tmp_path):
    from types import SimpleNamespace
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ai_inspector.facility_layout.authorization import FacilityPrincipal
    from ai_inspector.facility_layout.site_imagery import create_site_imagery_router
    doc=fixture(); original=copy.deepcopy(doc); reads=[]
    service=SimpleNamespace(layout_repository=SimpleNamespace(root=tmp_path),
        get_layout=lambda principal, site, identity: reads.append((site,identity)))
    principal=FacilityPrincipal('reader','tenant-a',('site-a',),('viewer',))
    app=FastAPI();app.include_router(create_site_imagery_router(service=service,principal_resolver=lambda request:principal))
    with TestClient(app) as client:
        url='/api/facility-layouts/site-a/'+doc['layoutId']+'/site-analysis'
        response=client.post(url,json={'layout':doc})
        assert response.status_code==200 and response.json()['metrics']['lotAreaSquareMeters']==8000
        wrong=copy.deepcopy(doc);wrong['layoutId']='wrong-layout'
        assert client.post(url,json={'layout':wrong}).status_code==400
        assert client.post(url.replace('site-a','foreign-site'),json={'layout':doc}).status_code==404
    assert doc==original and len(reads)==2
