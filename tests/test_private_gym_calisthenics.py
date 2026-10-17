from copy import deepcopy
import pytest

from ai_inspector.facility_layout.host import _asset
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools.add_private_gym_calisthenics import A, WALL, OLD_RACK, PAD, operations, yaw


def fixture():
    wall=_asset(asset_id='asset-wall',display_name='Support Wall',category='Building Structures',
        width=8,depth=.25,height=3,description='')
    wall['definition']['tags']=['wall']
    assets=[wall]
    for kind,width,depth,height in [('wall-bar',1.34216833,.602999926,2.554999948),
                                   ('pushup-supports',.66,.811393968,.432466798)]:
        assets.append(_asset(asset_id=A+kind,display_name=kind,category='Gym Equipment',
            width=width,depth=depth,height=height,description=''))
    before=dict(placements=[dict(placementId=WALL,assetId=wall['assetId'],
        assetDefinitionRevision=wall['assetDefinitionRevision'],positionMode='manual',
        transform=dict(position=dict(x=75,y=0,z=61),quaternion=yaw(0),scale=1))])
    return before,{a['assetId']:a for a in assets}


def test_relocates_wall_and_pad_and_only_replaces_old_rack():
    before,catalog=fixture()
    snapshot=deepcopy(before)
    ops=operations(before,catalog)
    assert before==snapshot
    assert len(ops)==10
    assert ops[0]==dict(op='delete_placement',placementId=OLD_RACK)
    assert ops[1]['placementId']==WALL and ops[1]['position']==dict(x=44.2,y=0,z=67)
    assert ops[2]['quaternion']==yaw(270)
    assert ops[3]['markingId']==PAD
    assert set(ops[3]['patch'])=={'transform'}


def test_three_matching_bars_with_one_support_pair_per_station():
    before,catalog=fixture()
    additions=[op['placement'] for op in operations(before,catalog) if op['op']=='place_asset']
    assert len({p['placementId'] for p in additions})==6
    for kind in ['wall-bar','pushup-supports']:
        stations=[p for p in additions if p['assetId']==A+kind]
        assert len(stations)==3
        assert [p['transform']['position']['z'] for p in stations]==[64.5,67,69.5]
        assert all(p['transform']['scale']==1 and p['transform']['position']['y']==0 for p in stations)


def test_all_three_mounts_validate_on_relocated_negative_z_face():
    before,catalog=fixture()
    ops=operations(before,catalog)
    wall=deepcopy(before['placements'][0])
    wall['transform']['position']=ops[1]['position']
    wall['transform']['quaternion']=ops[2]['quaternion']
    additions=[op['placement'] for op in ops if op['op']=='place_asset']
    layout=dict(placements=[wall,*additions],zones=[],routes=[],floorMarkings=[])
    shell=dict(features=[dict(featureId='floor',featureKind='floor_surface',geometry=dict(elevation=0,
        boundary=[dict(x=x,z=z) for x,z in [(44,40),(82,40),(82,72),(44,72)]]))])
    findings=diagnose_layout(layout,list(catalog.values()),shell=shell)['findings']
    assert not [f for f in findings if f['severity']=='error']
    assert sum(f['code']=='wall_attachment_safety_unverified' for f in findings)==3


def test_mount_references_exact_wall_revision_and_outward_face():
    before,catalog=fixture()
    for op in operations(before,catalog):
        p=op.get('placement',{})
        if p.get('assetId')==A+'wall-bar':
            r=p['snapRelationship']
            assert r['supportPlacementId']==WALL
            assert r['supportAssetDefinitionRevision']==before['placements'][0]['assetDefinitionRevision']
            assert r['face']=='negative_z'
            assert p['transform']['quaternion']==yaw(90)
            assert p['transform']['position']['x']==pytest.approx(44.6365)


def test_missing_asset_does_not_produce_partial_plan():
    before,catalog=fixture()
    del catalog[A+'wall-bar']
    with pytest.raises(KeyError):
        operations(before,catalog)
