from copy import deepcopy
import math
import pytest
from tools import add_factory02_office_fans as fans


def inputs(monkeypatch):
    monkeypatch.setattr(fans, 'layout_revision', lambda _: fans.BASE_REVISION)
    doc = {'layoutId': fans.LAYOUT_ID, 'placements': [
        {'placementId': f'pl-independent-office-{n}-chair',
         'transform': {'position': {'x': 57.55, 'y': 0, 'z': z}}} for n, z in ((1, 9), (2, 12.5))]}
    catalog = {fans.ASSET_ID: {'assetDefinitionRevision': 'fan-revision',
               'definition': {'readiness': {'placementReady': {'value': True}}}}}
    return doc, catalog


def test_two_distinct_revision_bound_fans_leave_inputs_unchanged(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    before = deepcopy((doc, catalog))
    ops = fans.fan_operations(doc, catalog)
    assert len(ops) == 2
    assert {op['placement']['placementId'] for op in ops} == {fans.PREFIX + '1', fans.PREFIX + '2'}
    assert all(op['placement']['assetDefinitionRevision'] == 'fan-revision' for op in ops)
    assert all('zoneId' not in op['placement'] for op in ops)
    assert (doc, catalog) == before
    assert ops == fans.fan_operations(doc, catalog)


def test_fan_fronts_face_their_workstations(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    for op, chair in zip(fans.fan_operations(doc, catalog), doc['placements']):
        t = op['placement']['transform']
        q = t['quaternion']
        dx = chair['transform']['position']['x'] - t['position']['x']
        dz = chair['transform']['position']['z'] - t['position']['z']
        length = math.hypot(dx, dz)
        assert 1 - 2 * q['y']**2 == pytest.approx(dx / length)
        assert -2 * q['y'] * q['w'] == pytest.approx(dz / length)


def test_reference_and_stale_base_rejected(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    with pytest.raises(ValueError, match='has changed'):
        fans.fan_operations(dict(doc, layoutId=fans.MANUAL_ID), catalog)
    monkeypatch.setattr(fans, 'layout_revision', lambda _: 'newer')
    with pytest.raises(ValueError, match='has changed'):
        fans.fan_operations(doc, catalog)


def test_unready_fan_rejected(monkeypatch):
    doc, catalog = inputs(monkeypatch)
    catalog[fans.ASSET_ID]['definition']['readiness']['placementReady']['value'] = False
    with pytest.raises(ValueError, match='not placement-ready'):
        fans.fan_operations(doc, catalog)
