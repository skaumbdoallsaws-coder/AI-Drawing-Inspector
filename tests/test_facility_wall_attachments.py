from copy import deepcopy
import math

import pytest

from ai_inspector.facility_layout.host import _asset
from ai_inspector.facility_layout.spatial import diagnose_layout
from ai_inspector.facility_layout.wall_attachments import validate_relationship


def scene(yaw=0, face='positive_z'):
    wall=_asset(asset_id='asset-wall',display_name='Wall',category='Building Structures',width=8,depth=.3,height=5,description='')
    wall['definition']['tags']=['wall']
    equipment=_asset(asset_id='asset-mounted',display_name='Mounted',category='Equipment',width=1,depth=2,height=1,description='')
    def placement(pid,asset,x,y,z,angle):
        r=math.radians(angle)/2
        return dict(placementId=pid,assetId=asset['assetId'],assetDefinitionRevision=asset['assetDefinitionRevision'],
            transform=dict(position=dict(x=x,y=y,z=z),quaternion=dict(x=0,y=math.sin(r),z=0,w=math.cos(r)),scale=1),
            positionMode='manual',snapRelationship=None,metadata={})
    angle=math.radians(yaw);sign=1 if face=='positive_z' else -1
    support=placement('pl-wall',wall,5,0,5,yaw)
    child=placement('pl-mounted',equipment,5+math.sin(angle)*sign*1.155,2,5+math.cos(angle)*sign*1.155,
                    yaw+(0 if sign==1 else 180))
    child['snapRelationship']=dict(family='wall_attachment',supportPlacementId='pl-wall',
        supportAssetDefinitionRevision=wall['assetDefinitionRevision'],face=face,localX=0,localY=2,normalGapMeters=.005)
    layout=dict(placements=[support,child],zones=[],routes=[],floorMarkings=[])
    shell=dict(features=[dict(featureId='floor',featureKind='floor_surface',geometry=dict(elevation=0,
        boundary=[dict(x=0,z=0),dict(x=10,z=0),dict(x=10,z=10),dict(x=0,z=10)]))])
    return layout,[wall,equipment],shell


def codes(layout,assets,shell):
    return {f['code'] for f in diagnose_layout(layout,assets,shell=shell)['findings'] if f['severity']=='error'}


@pytest.mark.parametrize('yaw',[0,90,180,270])
@pytest.mark.parametrize('face',['positive_z','negative_z'])
def test_upright_wall_attachment_on_both_faces(yaw,face):
    layout,assets,shell=scene(yaw,face)
    assert not codes(layout,assets,shell)
    findings=diagnose_layout(layout,assets,shell=shell)['findings']
    assert any(f['code']=='wall_attachment_safety_unverified' for f in findings)


@pytest.mark.parametrize('failure',['position','yaw','revision','missing','cycle','scale','no-contact','unsupported-asset','off-center'])
def test_invalid_attachment_does_not_bypass_floor_checks(failure):
    layout,assets,shell=scene()
    parent,child=layout['placements'];r=child['snapRelationship']
    if failure=='position': child['transform']['position']['y']+=.1
    elif failure=='yaw': child['transform']['quaternion']=dict(x=0,y=1,z=0,w=0)
    elif failure=='revision':r['supportAssetDefinitionRevision']='stale'
    elif failure=='missing':r['supportPlacementId']='pl-missing'
    elif failure=='cycle':parent['snapRelationship']=dict(r,supportPlacementId=child['placementId'])
    elif failure=='scale':child['transform']['scale']=2
    elif failure=='no-contact':child['transform']['position']['y']=6;r['localY']=6
    elif failure=='unsupported-asset':assets[0]['definition']['tags']=[]
    elif failure=='off-center':assets[1]['definition']['geometry']['aabb']['minimum']['x']-=.2
    errors=codes(layout,assets,shell)
    assert 'invalid_wall_attachment' in errors
    assert ('asset_geometry_missing' if failure=='scale' else 'unsupported_mounting_surface') in errors


def test_bare_floating_asset_still_rejected_and_other_collision_not_exempted():
    layout,assets,shell=scene()
    child=layout['placements'][1]
    child['snapRelationship']=None
    assert 'unsupported_mounting_surface' in codes(layout,assets,shell)
    layout,assets,shell=scene()
    other=deepcopy(layout['placements'][1]);other['placementId']='pl-other';other['snapRelationship']=None
    layout['placements'].append(other)
    assert 'placement_collision' in codes(layout,assets,shell)


@pytest.mark.parametrize('field,value',[('normalGapMeters',.5),('normalGapMeters',float('nan')),('localX',True),('localX',10**1000),('face','top')])
def test_wall_attachment_closed_field_contract(field,value):
    layout,_,_=scene();relationship=layout['placements'][1]['snapRelationship'];relationship[field]=value
    with pytest.raises(ValueError):validate_relationship(relationship)
