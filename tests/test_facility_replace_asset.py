from copy import deepcopy
import pytest
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tests.test_facility_component_materials import material
from tests.test_facility_decals import document
from tests.test_facility_layout_api import _client, _layout, _placement_operation, _resolved_asset


def operation(identifier):
    return dict(op='replace_asset',placementId=identifier,assetId='asset-replacement',assetDefinitionRevision='b'*64,keepAppearance=True)


def test_identity_position_rotation_label_and_other_items_preserved():
    doc=document();first=_placement_operation()['placement']
    first.update(componentMaterials=material(),appearance=dict(color='#c99b39'))
    first.setdefault('metadata',{})['instanceLabel']='Seat 04'
    second=deepcopy(first);second['placementId']='pl-other';doc['placements']=[first,second]
    result=apply_facility_layout_operations(doc,[operation(first['placementId'])])['document']
    replacement=result['placements'][0]
    assert replacement['placementId']==first['placementId']
    assert replacement['transform']==first['transform']
    assert replacement['metadata']['instanceLabel']=='Seat 04'
    assert replacement['appearance']==first['appearance']
    assert 'componentMaterials' not in replacement
    assert result['placements'][1]==second
    assert result['extensions']==doc['extensions']
    reset=apply_facility_layout_operations(doc,[dict(operation(first['placementId']),keepAppearance=False)])['document']
    assert 'appearance' not in reset['placements'][0]


def test_referenced_parent_rejected_atomically():
    doc=document();first=_placement_operation()['placement'];child=deepcopy(first)
    child['placementId']='pl-child';child['snapRelationship']=dict(supportPlacementId=first['placementId'])
    doc['placements']=[first,child];before=deepcopy(doc)
    with pytest.raises(Exception,match='Detach'):apply_facility_layout_operations(doc,[operation(first['placementId'])])
    assert doc==before


@pytest.mark.parametrize('patch',[dict(assetDefinitionRevision='latest'),dict(keepAppearance='yes'),dict(placementId='pl-missing')])
def test_invalid_replacement(patch):
    doc=document();first=_placement_operation()['placement'];doc['placements']=[first]
    with pytest.raises(Exception):apply_facility_layout_operations(doc,[dict(operation(first['placementId']),**patch)])


def test_http_preview_is_read_only_and_rejects_outside_floor(tmp_path):
    client,service,shell,policy=_client(tmp_path)
    doc=_layout(shell,policy);doc['placements']=[_placement_operation()['placement']]
    created=client.post('/api/facility-layouts/site-a',json=dict(layout=doc)).json()
    url='/api/facility-layouts/site-a/fl-api-cell'
    op=operation(doc['placements'][0]['placementId'])
    payload=dict(baseRevision=created['revision'],operations=[op])
    response=client.post(url+'/preview',json=payload)
    assert response.status_code==200,response.text
    assert client.get(url).json()['revision']==created['revision']
    def resolver(_principal,_site,asset_id,revision):
        result=_resolved_asset(asset_id,revision)
        if asset_id=='asset-replacement':
            result['definition']['geometry']['footprintPolygons']=[[dict(x=-100,z=-100),dict(x=100,z=-100),dict(x=100,z=100),dict(x=-100,z=100)]]
        return result
    service.asset_definition_resolver=resolver
    rejected=client.post(url+'/preview',json=payload)
    assert rejected.status_code==422,rejected.text
    assert client.get(url).json()['revision']==created['revision']
    service.asset_definition_resolver=lambda *args: None
    assert client.post(url+'/preview',json=payload).status_code>=400
    assert client.get(url).json()['revision']==created['revision']
