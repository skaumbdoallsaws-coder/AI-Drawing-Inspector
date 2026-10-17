from copy import deepcopy
import pytest
from tools import update_private_gym_reception as reception


def fixture():
    placements = [dict(placementId=pid, assetId=aid) for pid, aid in reception.REMOVED.items()]
    placements += [dict(placementId='pl-2f8c760de4adbb1a83cc1629',
        assetId='asset-private-gym-reception-congo-mural',
        transform=dict(position=dict(x=6, y=0, z=.3))),
        dict(placementId='pl-gym-pool-swimming-pool', assetId='keep-pool'),
        dict(placementId='pl-gym-pool-corner-jacuzzi', assetId='keep-jacuzzi')]
    before = dict(placements=placements, zones=[dict(zoneId='keep-zone')], floorMarkings=[],
        extensions=dict(facilityPerimeterWalls=dict(settings=dict(exteriorFinish=dict(artworks=[
            dict(artworkId='apex-interior-a01', edge=3, side='interior', startMeters=21.775, widthMeters=2.45)])))))
    catalog = {aid: dict(assetDefinitionRevision=aid+'-exact-revision') for aid in (reception.DESK, reception.SOFA)}
    return before, catalog


def test_replaces_only_old_desk_chair_and_billiards_table():
    before, catalog = fixture()
    original = deepcopy(before)
    ops = reception.operations(before, catalog)
    assert before == original
    assert {o['placementId'] for o in ops if o['op'] == 'delete_placement'} == reception.REMOVED.keys()
    added = [o['placement'] for o in ops if o['op'] == 'place_asset']
    assert len(added) == 2
    for p in added:
        assert p['assetDefinitionRevision'] == catalog[p['assetId']]['assetDefinitionRevision']
        assert p['transform']['scale'] == 1
    assert added[0]['transform']['position'] == dict(x=6, y=0, z=2.4)
    assert added[1]['transform']['quaternion'] == reception.yaw(90)


@pytest.mark.parametrize('change', ['wrong_old_asset', 'moved_flag', 'moved_lion', 'duplicate', 'missing_asset'])
def test_changed_context_rejects_before_any_edit(change):
    before, catalog = fixture()
    if change == 'wrong_old_asset':
        before['placements'][0]['assetId'] = 'not-billiards'
    elif change == 'moved_flag':
        before['placements'][3]['transform']['position']['x'] = 8
    elif change == 'moved_lion':
        before['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']['artworks'][0]['edge'] = 0
    elif change == 'duplicate':
        before['placements'].append(dict(placementId='pl-gym-reception-set'))
    else:
        del catalog[reception.DESK]
    original = deepcopy(before)
    with pytest.raises((AssertionError, KeyError)):
        reception.operations(before, catalog)
    assert before == original


def test_audit_preserves_pool_and_artwork_and_rejects_collateral_changes(monkeypatch):
    before, catalog = fixture()
    after = deepcopy(before)
    after['placements'] = [p for p in after['placements'] if p['placementId'] not in reception.REMOVED]
    after['placements'] += [o['placement'] for o in reception.operations(before, catalog) if o['op'] == 'place_asset']
    monkeypatch.setattr(reception, 'footprint', lambda p, _: (4.4, 1.63, 7.6, 3.17)
        if p['assetId'] == reception.DESK else (.414, 5.98, .986, 8.02))
    assert reception.audit(before, after, catalog)['swimmingPoolUnchanged']
    after['zones'][0]['zoneId'] = 'changed'
    with pytest.raises(AssertionError, match='Unrelated layout change'):
        reception.audit(before, after, catalog)
