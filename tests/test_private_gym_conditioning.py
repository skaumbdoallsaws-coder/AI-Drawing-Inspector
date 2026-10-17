from copy import deepcopy
import pytest
from ai_inspector.facility_layout.canonical import canonicalize_quaternion
from tools.add_private_gym_conditioning import A, TIRES, operations


def fixture():
    before=dict(placements=[dict(placementId=pid,transform=dict(position=dict(x=x,y=0,z=56)))
        for pid,x in zip(TIRES,[54,59,64,68])],floorMarkings=[
            dict(markingId='fm-private-gym-fields-lane-distance-4',transform=dict(position=dict(x=70,z=47))),
            *[dict(markingId='fm-private-gym-fields-lane-number-'+str(i),transform=dict(position=dict(x=49,z=z)))
              for i,z in enumerate([44,46,48,50],1)]])
    catalog={A+k:dict(assetDefinitionRevision='revision-'+k) for k in ['sled','hammer']}
    return before,catalog


def test_exactly_eight_additions_without_mutating_input():
    before,catalog=fixture()
    snapshot=deepcopy(before)
    ops=operations(before,catalog)
    assert len(ops)==8 and all(o['op']=='place_asset' for o in ops)
    assert before==snapshot
    assert len({o['placement']['placementId'] for o in ops})==8


def test_sleds_follow_lane_centers_with_handles_at_start():
    before,catalog=fixture()
    sleds=[o['placement'] for o in operations(before,catalog) if o['placement']['assetId']==A+'sled']
    assert [p['transform']['position']['z'] for p in sleds]==[44,46,48,50]
    for p in sleds:
        assert p['transform']['position']['x']==70.65
        assert p['transform']['quaternion']==dict(x=0,y=0,z=0,w=1)
        assert p['assetDefinitionRevision']=='revision-sled'


def test_flat_hammers_are_aligned_in_front_of_each_tire():
    before,catalog=fixture()
    hammers=[o['placement'] for o in operations(before,catalog) if o['placement']['assetId']==A+'hammer']
    for p,x,pid in zip(hammers,[54,59,64,68],TIRES):
        assert p['transform']['position']==dict(x=x,y=0,z=54.7)
        assert p['metadata']['authoredReference']==pid
        assert p['transform']['quaternion']['y']==pytest.approx(2**-.5)
        assert p['transform']['quaternion']['x']==p['transform']['quaternion']['z']==0
        assert p['transform']['scale']==1


def test_orientations_survive_canonical_roundtrip():
    before,catalog=fixture()
    for op in operations(before,catalog):
        quaternion=op['placement']['transform']['quaternion']
        assert quaternion==canonicalize_quaternion(quaternion)


def test_missing_tire_or_lane_does_not_fall_back_to_invented_coordinates():
    before,catalog=fixture()
    before['placements'].pop()
    with pytest.raises(KeyError):
        operations(before,catalog)
    before,catalog=fixture()
    before['floorMarkings'].pop()
    with pytest.raises(KeyError):
        operations(before,catalog)
