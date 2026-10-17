from copy import deepcopy
import json
from pathlib import Path
import pytest
from shapely.geometry import box
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.plan_settings import shell_with_plan_boundary
from ai_inspector.facility_layout.spatial import diagnose_layout
from tools import add_factory02_kitchen_walls as kitchen


def inputs(monkeypatch):
    doc = json.loads((Path(__file__).parent / 'fixtures/facility_layout/empty_cell.json').read_text())
    doc['layoutId'] = kitchen.LAYOUT_ID
    doc['zones'] = []
    doc['placements'] = [{
        'placementId': kitchen.KITCHEN_ID, 'assetId': 'asset-kitchen-assembly',
        'assetDefinitionRevision': 'a' * 64, 'positionMode': 'manual', 'metadata': {},
        'snapRelationship': None, 'transform': {
            'position': {'x': 57.3, 'y': 0, 'z': 32},
            'quaternion': {'x': 0, 'y': 0, 'z': 0, 'w': 1}, 'scale': 1}}]
    monkeypatch.setattr(kitchen, 'layout_revision', lambda _: kitchen.BASE_REVISION)
    return doc


def test_bounded_operations_preserve_input_and_only_move_kitchen(monkeypatch):
    doc = inputs(monkeypatch)
    before = deepcopy(doc)
    ops = kitchen.kitchen_operations(doc)
    assert [o['op'] for o in ops] == ['move_placement', 'add_zone', 'set_perimeter_walls', 'add_aisle']
    result = apply_facility_layout_operations(doc, ops)['document']
    assert len(result['placements']) == 1
    assert result['placements'][0]['transform']['position'] == {'x': 57.3, 'y': 0, 'z': 32.8}
    assert result['placements'][0]['transform']['quaternion'] == doc['placements'][0]['transform']['quaternion']
    assert doc == before
    assert ops == kitchen.kitchen_operations(doc)


def test_wall_dimensions_and_full_height_entrance(monkeypatch):
    doc = inputs(monkeypatch)
    result = apply_facility_layout_operations(doc, kitchen.kitchen_operations(doc))['document']
    walls = kitchen.wall_shape(result)
    assert walls.bounds == pytest.approx((53.725, 29.425, 61.075, 36.175))
    assert not walls.intersects(box(56.401, 29.4, 58.199, 29.6))
    assert walls.intersects(box(56.2, 29.45, 56.3, 29.55))
    assert walls.intersects(box(58.3, 29.45, 58.4, 29.55))
    assert result['extensions'][kitchen.KEY]['settings']['heightMeters'] == 2.8


def test_real_spatial_validator_accepts_entrance_and_rejects_sealed_wall(monkeypatch):
    doc = inputs(monkeypatch)
    ops = kitchen.kitchen_operations(doc)
    result = apply_facility_layout_operations(doc, ops)['document']
    asset = {'assetId': 'asset-kitchen-assembly', 'geometry': {
        'footprintPolygons': [[dict(x=-1,z=-1),dict(x=1,z=-1),dict(x=1,z=1),dict(x=-1,z=1)]],
        'heightInterval': {'minimumY': 0, 'maximumY': 2}}, 'clearances': []}

    def codes(layout):
        return {f['code'] for f in diagnose_layout(layout, [asset],
            shell=shell_with_plan_boundary({'features': []}, layout))['findings']}

    assert not {'aisle_shell_obstructed', 'shell_obstacle_collision'} & codes(result)
    sealed = deepcopy(ops[2])
    sealed['wallSettings']['openings'] = []
    closed = apply_facility_layout_operations(result, [sealed])['document']
    assert 'aisle_shell_obstructed' in codes(closed)
    collision = apply_facility_layout_operations(result, [{
        'op': 'move_placement', 'placementId': kitchen.KITCHEN_ID,
        'position': {'x': 54, 'y': 0, 'z': 32.8}}])['document']
    assert 'shell_obstacle_collision' in codes(collision)


def test_wrong_layout_stale_base_and_existing_walls_fail_closed(monkeypatch):
    doc = inputs(monkeypatch)
    with pytest.raises(ValueError, match='has changed'):
        kitchen.kitchen_operations(dict(doc, layoutId=kitchen.MANUAL_ID))
    protected = deepcopy(doc)
    protected.setdefault('extensions', {})[kitchen.KEY] = {}
    with pytest.raises(ValueError, match='must not be overwritten'):
        kitchen.kitchen_operations(protected)
    monkeypatch.setattr(kitchen, 'layout_revision', lambda _: 'newer')
    with pytest.raises(ValueError, match='has changed'):
        kitchen.kitchen_operations(doc)
