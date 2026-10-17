from copy import deepcopy
import pytest
from tools.private_gym_training_art import ARTWORKS, audit


def test_artwork_order_matches_the_gym_floor_view():
    assert [a[0] for a in ARTWORKS]==['eagle','warrior','panther']
    assert [a[-1] for a in ARTWORKS]==sorted(a[-1] for a in ARTWORKS)


def test_scoped_audit_preserves_reception_and_every_other_field():
    before=dict(updatedAt='old',placements=[dict(placementId=str(i),assetId='old',assetDefinitionRevision='1',transform={'x':i}) for i in range(4)])
    refs={str(i):dict(assetId='art-'+str(i),assetDefinitionRevision='2') for i in range(3)}
    after=deepcopy(before)
    for p in after['placements'][:3]:p.update(refs[p['placementId']])
    audit(before,after,refs)
    after['placements'][3]['assetId']='changed-reception'
    with pytest.raises(AssertionError):audit(before,after,refs)


def test_scoped_audit_rejects_moving_a_target_wall():
    before=dict(updatedAt='old',placements=[dict(placementId=str(i),assetId='old',transform={'x':i}) for i in range(3)])
    refs={str(i):dict(assetId='art-'+str(i),assetDefinitionRevision='2') for i in range(3)}
    after=deepcopy(before)
    for p in after['placements']:p.update(refs[p['placementId']])
    after['placements'][0]['transform']['x']=99
    with pytest.raises(AssertionError):audit(before,after,refs)


def test_single_wall_update_requires_explicit_scope():
    before=dict(updatedAt='old',placements=[dict(placementId='eagle',assetId='old'),dict(placementId='warrior',assetId='keep')])
    after=deepcopy(before);after['placements'][0]['assetId']='wide-eagle'
    refs={'eagle':dict(assetId='wide-eagle')}
    with pytest.raises(AssertionError):audit(before,after,refs)
    audit(before,after,refs,expected_count=1)
    after['placements'][1]['assetId']='changed'
    with pytest.raises(AssertionError):audit(before,after,refs,expected_count=1)
