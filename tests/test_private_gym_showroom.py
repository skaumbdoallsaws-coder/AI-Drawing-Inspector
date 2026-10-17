from copy import deepcopy
import pytest
from tools.add_private_gym_showroom import ASSET, PLACEMENT, PAD, operations


def fixture():
    return dict(placements=[],floorMarkings=[dict(markingId=PAD,width=9,depth=6,
        transform=dict(position=dict(x=47.4,y=.003,z=67),rotationDegrees=270))]),{ASSET:dict(assetDefinitionRevision='reviewed-revision')}


def test_adds_only_corrected_assembly_without_touching_existing_state():
    before,catalog=fixture()
    original=deepcopy(before)
    ops=operations(before,catalog)
    assert before==original
    assert len(ops)==1 and ops[0]['op']=='place_asset'
    p=ops[0]['placement']
    assert p['placementId']==PLACEMENT and p['assetId']==ASSET
    assert p['assetDefinitionRevision']=='reviewed-revision'
    assert p['transform']==dict(position=dict(x=49.1,y=0,z=70),quaternion=dict(x=0,y=0,z=0,w=1),scale=1)
    assert 'appearance' not in p


@pytest.mark.parametrize('change',['pad_position','pad_size','duplicate'])
def test_stale_review_or_duplicate_stops_without_partial_operations(change):
    before,catalog=fixture()
    if change=='pad_position':before['floorMarkings'][0]['transform']['position']['x']+=1
    elif change=='pad_size':before['floorMarkings'][0]['width']=5
    else:before['placements'].append(dict(placementId=PLACEMENT))
    with pytest.raises(AssertionError):operations(before,catalog)


def test_missing_catalog_asset_cannot_be_substituted_with_the_car():
    before,_=fixture()
    with pytest.raises(KeyError):
        operations(before,{'asset-gym-fitness-centre-weights':dict(assetDefinitionRevision='wrong-model')})
