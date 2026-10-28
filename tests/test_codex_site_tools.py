import asyncio
from copy import deepcopy
import json
import pytest
from jsonschema import Draft202012Validator
from ai_inspector.codex_runtime.assisted_tools import FacilityEditGateway
from ai_inspector.codex_runtime.site_tools import read_site, tool_specs
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.facility_layout.site_context import KEY
from tests.test_codex_assisted_tools import setup
from tests.test_facility_site_property import fixture
from tests.test_facility_site_areas import area
from tests.test_facility_operation_proposals import approve, apply, propose


def seeded(setup):
    host,old,saved=setup
    context=fixture()['extensions'][KEY]
    context['property']['setbacksMeters']={'street':0,'side':0,'rear':0}
    saved=host.service.apply_operations(host.principal(),old.reference['siteId'],old.reference['layoutId'],
        saved['revision'],[{'op':'set_site_context','siteContext':context}])
    gateway=FacilityEditGateway(host.agent_runtime,host.principal(),{**old.reference,'revision':saved['revision']},turn_id='site-test')
    return host,gateway,host.service.get_layout(host.principal(),old.reference['siteId'],old.reference['layoutId'])


def test_read_and_fit_are_revision_bound_pure_and_have_closed_contracts(setup):
    host,gateway,saved=seeded(setup)
    for spec in tool_specs():Draft202012Validator.check_schema(spec['input_schema'])
    read=asyncio.run(gateway.call('inspect_site_context',{}))
    assert read['ok'] and read['data']['savedLayoutOnly'] and read['data']['readOnly']
    result=asyncio.run(gateway.call('analyze_site_fit',{'widthMeters':24,'depthMeters':18,'parkingCount':10}))
    assert result['ok'] and result['data']['candidates']
    assert not asyncio.run(gateway.call('inspect_site_context',{'file':'C:/private'}))['ok']
    assert host.service.get_layout(host.principal(),gateway.reference['siteId'],gateway.reference['layoutId'])==saved
    host.service.apply_operations(host.principal(),gateway.reference['siteId'],gateway.reference['layoutId'],
        saved['revision'],[{'op':'rename_layout','displayName':'New revision'}])
    assert asyncio.run(gateway.call('inspect_site_context',{}))['error']['code']=='codex_document_unavailable'


def test_site_preview_requires_approval_reports_candidate_findings_and_never_saves(setup):
    host,gateway,saved=seeded(setup);gateway.edit_mode='direct'
    result=asyncio.run(gateway.call('preview_facility_operations',{'operations':[
        {'op':'upsert_site_area','area':area('parking',95,60,20,20)}]}))
    assert result['ok'],result
    assert result['data']['approvalRequired'] and not result['data']['directApplyPolicy']['eligible']
    assert any(f['code']=='site_area_outside_property' for f in result['data']['validation']['siteContext']['findings'])
    assert host.service.get_layout(host.principal(),gateway.reference['siteId'],gateway.reference['layoutId'])==saved


@pytest.mark.parametrize('change',['origin','imagery','remove'])
def test_agent_cannot_change_location_or_imagery_even_through_backend_proposals(setup,change):
    host,gateway,saved=seeded(setup)
    context=deepcopy(saved['layout']['extensions'][KEY])
    if change=='origin':context['georeference']['originLatitude']+=.001
    elif change=='imagery':
        context['imagery']=[{'imageId':'a'*64,'imagePath':'/api/facility-site-imagery/'+gateway.reference['siteId']+'/'+('a'*64)+'.jpg',
            'source':'usgs_naip','captured':None,'geoBounds':{'south':44.999,'north':45.001,'west':-93.001,'east':-92.999},
            'widthPixels':1000,'heightPixels':1000}]
    else:context=None
    with pytest.raises(FacilityLayoutError) as error:
        propose((host.service,host.principal()),operations=[{'op':'set_site_context','siteContext':context}])
    assert error.value.code=='site_location_manual_only'
    assert host.service.get_layout(host.principal(),gateway.reference['siteId'],gateway.reference['layoutId'])==saved


def test_approved_site_transaction_and_exact_receipt_undo(setup):
    host,gateway,saved=seeded(setup);context=(host.service,host.principal())
    operations=[{'op':'set_building_pose','buildingPose':{'x':15,'z':30,'bearingDegrees':30}},
        {'op':'upsert_site_area','area':area('parking',65,45,20,20)}]
    result=asyncio.run(gateway.call('preview_facility_operations',{'operations':operations}))
    assert result['ok'],result
    preview=host.service.get_layout_proposal_preview(host.principal(),gateway.reference['siteId'],gateway.reference['layoutId'],result['data']['proposalId'])
    assert not result['data']['validation']['siteContext']['findings']
    with pytest.raises(FacilityLayoutError):approve(context,preview,explicit=False)
    committed=apply(context,preview,approve(context,preview))
    assert len(committed['layout']['extensions'][KEY]['areas'])==1
    assert committed['layout']['placements']==saved['layout']['placements']
    undo=propose(context,undo_receipt_id=committed['receipt']['receiptId'])
    restored=apply(context,undo,approve(context,undo,key='site-undo'),key='site-undo')
    assert restored['layout']['extensions'][KEY]==saved['layout']['extensions'][KEY]


def test_inspection_pages_geometry_and_bounds_diagnostic_output():
    doc=fixture();doc['extensions'][KEY]['areas']=[area('a'+str(i),60,20,20,20) for i in range(64)]
    result=read_site(doc,'inspect_site_context',{'includeAreaBoundaries':True})
    assert len(result['areas'])==4 and result['nextAreaOffset']==4
    assert result['analysis']['findingsTruncated'] and len(result['analysis']['findings'])==40
    assert len(json.dumps(result).encode()) < 65536
    last=read_site(doc,'inspect_site_context',{'areaOffset':60})
    assert last['nextAreaOffset'] is None and 'boundary' not in last['areas'][0]


def test_agent_site_edits_keep_reference_layers_and_cannot_remove_them(setup):
    host,gateway,saved=seeded(setup);context=(host.service,host.principal())
    site=gateway.reference['siteId'];base=deepcopy(saved['layout']['extensions'][KEY])
    layer={'layer':'flood','imageId':'d'*64,'imagePath':'/api/facility-site-imagery/'+site+'/'+('d'*64)+'.png',
        'source':'fema_nfhl','captured':'2026-10-22','geoBounds':{'south':44.999,'north':45.001,'west':-93.001,'east':-92.999},
        'widthPixels':600,'heightPixels':600,'detail':'FEMA flood hazard zones'}
    host.service.apply_operations(host.principal(),site,gateway.reference['layoutId'],saved['revision'],
        [{'op':'set_site_context','siteContext':{**base,'overlays':[layer]}}])
    # Sage's schema has no overlays: an edit that leaves them out keeps the stored ones.
    edited={**base,'property':{**base['property'],'setbacksMeters':{'street':5,'side':0,'rear':0}}}
    proposal=propose(context,operations=[{'op':'set_site_context','siteContext':edited}])
    kept=proposal['alternative']['operations'][0]['siteContext']['overlays']
    assert [item['layer'] for item in kept]==['flood']
    # Dropping or replacing them is a location-level change, refused like imagery.
    with pytest.raises(FacilityLayoutError) as error:
        propose(context,operations=[{'op':'set_site_context','siteContext':{**edited,'overlays':[]}}])
    assert error.value.code=='site_location_manual_only'


def test_agent_site_edits_keep_roads_and_read_them(setup, monkeypatch):
    from tests.test_facility_site_roads import box, tiger
    from ai_inspector.facility_layout.site_roads import fetch_roads
    host,gateway,saved=seeded(setup);context=(host.service,host.principal())
    site=gateway.reference['siteId'];base=deepcopy(saved['layout']['extensions'][KEY])
    tiger(monkeypatch);roads=fetch_roads(box())
    stored=host.service.apply_operations(host.principal(),site,gateway.reference['layoutId'],saved['revision'],
        [{'op':'set_site_context','siteContext':{**base,'roads':roads}}])
    read=read_site(stored['layout'],'inspect_site_context',{})
    assert [item['kind'] for item in read['roads']['items']].count('arterial')==2
    edited={**base,'property':{**base['property'],'setbacksMeters':{'street':5,'side':0,'rear':0}}}
    proposal=propose(context,operations=[{'op':'set_site_context','siteContext':edited}])
    assert len(proposal['alternative']['operations'][0]['siteContext']['roads']['items'])==5
    with pytest.raises(FacilityLayoutError) as error:
        propose(context,operations=[{'op':'set_site_context','siteContext':{**edited,'roads':{**roads,'items':[]}}}])
    assert error.value.code=='site_location_manual_only'
