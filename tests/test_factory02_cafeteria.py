from copy import deepcopy
import math
import pytest
from tools import add_factory02_cafeteria as cafe


def inputs(monkeypatch):
    monkeypatch.setattr(cafe, 'layout_revision', lambda _: cafe.BASE_REVISION)
    return {'layoutId': cafe.LAYOUT_ID}, {
        aid: {'assetDefinitionRevision': aid + '-revision',
              'definition': {'readiness': {'placementReady': {'value': True}}}}
        for aid in cafe.ASSET_IDS
    }


def test_exact_furniture_counts_and_revision_bound_operations(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    original = deepcopy((doc, catalog))
    ops = cafe.cafeteria_operations(doc, catalog)
    placements = [op['placement'] for op in ops if op['op'] == 'place_asset']
    assert len(ops) == 23
    assert len({p['placementId'] for p in placements}) == 21
    assert sum(p['assetId'] == cafe.TABLE for p in placements) == 4
    assert sum(p['assetId'] == cafe.CHAIR for p in placements) == 16
    assert sum(p['assetId'] == cafe.KITCHEN for p in placements) == 1
    assert all(p['assetDefinitionRevision'] == p['assetId'] + '-revision' for p in placements)
    assert all('zoneId' not in p for p in placements)
    assert cafe.cafeteria_operations(doc, catalog) == ops
    assert (doc, catalog) == original


def test_every_chair_faces_its_table(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    placements = [op['placement'] for op in cafe.cafeteria_operations(doc, catalog) if op['op'] == 'place_asset']
    by_id = {p['placementId']: p for p in placements}
    for p in placements:
        if p['assetId'] != cafe.CHAIR:
            continue
        table = by_id[p['placementId'].rsplit('-chair-', 1)[0]]['transform']['position']
        position, q = p['transform']['position'], p['transform']['quaternion']
        dx, dz = table['x'] - position['x'], table['z'] - position['z']
        length = math.hypot(dx, dz)
        assert 2 * q['y'] * q['w'] == pytest.approx(dx / length)
        assert 1 - 2 * q['y']**2 == pytest.approx(dz / length)


def test_kitchen_serving_side_faces_seating_and_access_joins_office_walk(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    ops = cafe.cafeteria_operations(doc, catalog)
    kitchen = next(op['placement'] for op in ops if op.get('placement', {}).get('assetId') == cafe.KITCHEN)
    q = kitchen['transform']['quaternion']
    assert -2 * q['y'] * q['w'] == pytest.approx(-1)
    assert all(z < kitchen['transform']['position']['z'] for _, z in cafe.TABLE_CENTERS)
    assert ops[-1]['aisle']['centerline'][-1] == {'x': 62, 'y': 0, 'z': 28.5}
    assert ops[-1]['aisle']['corridorWidth'] == 1.5


def test_wrong_layout_and_stale_base_fail_closed(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    with pytest.raises(ValueError, match='has changed'):
        cafe.cafeteria_operations(dict(doc, layoutId=cafe.MANUAL_ID), catalog)
    monkeypatch.setattr(cafe, 'layout_revision', lambda _: 'newer')
    with pytest.raises(ValueError, match='has changed'):
        cafe.cafeteria_operations(doc, catalog)


@pytest.mark.parametrize('aid', cafe.ASSET_IDS)
def test_unready_assets_are_rejected(monkeypatch, aid):
    doc, catalog = inputs(monkeypatch)
    catalog[aid]['definition']['readiness']['placementReady']['value'] = False
    with pytest.raises(ValueError, match='not placement-ready'):
        cafe.cafeteria_operations(doc, catalog)
