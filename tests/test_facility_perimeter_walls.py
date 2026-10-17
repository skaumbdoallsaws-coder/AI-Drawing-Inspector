from copy import deepcopy
import json
from pathlib import Path

import pytest
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from ai_inspector.facility_layout.perimeter_walls import KEY, compile_perimeter_walls, validate_perimeter_walls
from ai_inspector.facility_layout.plan_settings import default_plan_settings, shell_with_plan_boundary
from ai_inspector.facility_layout.operations import apply_facility_layout_operations, FacilityLayoutOperationError
from ai_inspector.facility_layout.spatial import shell_obstacle_records, diagnose_layout


def layout():
    value = json.loads((Path(__file__).parent / 'fixtures/facility_layout/empty_cell.json').read_text())
    value.setdefault('extensions', {})['facilityPlan'] = default_plan_settings()
    return value


def settings(**kwargs):
    return dict(boundarySource='plan', heightMeters=3, thicknessMeters=0.2, openings=[], **kwargs)


def geometry(value):
    return unary_union([Polygon([(p['x'], p['z']) for p in panel]) for panel in value['panels']])


def test_rectangular_ring_matches_exact_buffer_and_preserves_input():
    doc = layout(); before = deepcopy(doc)
    walls = compile_perimeter_walls(settings(), doc)
    floor = box(0, 0, 40, 30)
    expected = floor.buffer(0.1, join_style='mitre').difference(floor.buffer(-0.1, join_style='mitre'))
    assert geometry(walls).symmetric_difference(expected).area < 1e-8
    assert walls == compile_perimeter_walls(settings(), doc)
    assert doc == before


@pytest.mark.parametrize('points', [
    [(0,0),(10,0),(10,4),(4,4),(4,10),(0,10)],
    [(2,3),(18,6),(14,19),(-2,12)],
    [(0,10),(4,10),(4,4),(10,4),(10,0),(0,0)],
])
def test_concave_rotated_and_clockwise_perimeters(points):
    value = settings(); value.update(boundarySource='polygon', boundary=[dict(x=x,z=z) for x,z in points])
    walls = compile_perimeter_walls(value, layout())
    shape = Polygon(points)
    expected = shape.buffer(.1,join_style='mitre').difference(shape.buffer(-.1,join_style='mitre'))
    assert geometry(walls).symmetric_difference(expected).area < 1e-7


def test_opening_is_full_height_and_not_a_visual_only_gap():
    doc = layout(); value = settings()
    value['openings'] = [dict(edge=0,startMeters=5,endMeters=9)]
    doc['extensions'][KEY] = compile_perimeter_walls(value, doc)
    solid = geometry(doc['extensions'][KEY])
    assert not solid.intersects(box(5.01,-.05,8.99,.05))
    assert solid.intersects(box(1,-.05,2,.05))
    shell = shell_with_plan_boundary({'coordinateFrame':{'floorElevation':1},'features':[]},doc)
    records = shell_obstacle_records(shell)
    assert len(records) == len(doc['extensions'][KEY]['panels'])
    assert all(record.minimum_y == 1 and record.maximum_y == 4 for record in records)


@pytest.mark.parametrize('patch', [
    {'heightMeters':False}, {'heightMeters':float('nan')}, {'thicknessMeters':0},
    {'boundarySource':'guess'}, {'unexpected':1},
    {'openings':[dict(edge=8,startMeters=1,endMeters=2)]},
    {'openings':[dict(edge=0,startMeters=9,endMeters=5)]},
    {'openings':[dict(edge=0,startMeters=5,endMeters=90)]},
    {'openings':[dict(edge=0,startMeters=1,endMeters=5),dict(edge=0,startMeters=4,endMeters=8)]},
    {'boundarySource':'polygon','boundary':[dict(x=0,z=0),dict(x=4,z=4),dict(x=0,z=4),dict(x=4,z=0)]},
    {'boundarySource':'polygon','boundary':[dict(x=0,z=0),dict(x=0,z=0),dict(x=4,z=0)]},
])
def test_invalid_geometry_and_qualifiers_fail_closed(patch):
    value = settings(); value.update(patch)
    with pytest.raises(ValueError): compile_perimeter_walls(value, layout())


def test_operations_resize_remove_and_reject_stale_compiled_geometry():
    original = layout(); before = deepcopy(original)
    result = apply_facility_layout_operations(original,[dict(op='set_perimeter_walls',wallSettings=settings())])
    doc = result['document']; validate_perimeter_walls(doc)
    assert result['canonicalDiff']
    resized = apply_facility_layout_operations(doc,[dict(op='set_plan_settings',planSettings=default_plan_settings(width_meters=60))])['document']
    assert geometry(resized['extensions'][KEY]).bounds[2] == 60.1
    forged = deepcopy(doc); forged['extensions'][KEY]['panels'][0][0]['x'] += 1
    with pytest.raises(ValueError): validate_perimeter_walls(forged)
    removed = apply_facility_layout_operations(doc,[dict(op='set_perimeter_walls',wallSettings=None)])['document']
    assert KEY not in removed['extensions']
    assert original == before


def test_resize_rejects_opening_outside_new_edge_atomically():
    original = layout(); value = settings(); value['openings']=[dict(edge=0,startMeters=30,endMeters=35)]
    doc = apply_facility_layout_operations(original,[dict(op='set_perimeter_walls',wallSettings=value)])['document']
    before = deepcopy(doc)
    with pytest.raises(FacilityLayoutOperationError, match='startMeters'):
        apply_facility_layout_operations(doc,[dict(op='set_plan_settings',planSettings=default_plan_settings(width_meters=20))])
    assert doc == before


def test_polygon_snapshot_is_independent_of_plan_resize():
    original = layout(); value = settings()
    value.update(boundarySource='polygon',boundary=[dict(x=0,z=0),dict(x=10,z=0),dict(x=10,z=5)])
    doc = apply_facility_layout_operations(original,[dict(op='set_perimeter_walls',wallSettings=value)])['document']
    resized = apply_facility_layout_operations(doc,[dict(op='set_plan_settings',planSettings=default_plan_settings(width_meters=60))])['document']
    assert doc['extensions'][KEY] == resized['extensions'][KEY]


def test_wall_collision_and_aisle_obstruction_disappear_only_at_authored_opening():
    doc = layout(); doc['zones'] = []
    doc['placements'] = [{'placementId':'pl-test','assetId':'asset-test','assetDefinitionRevision':'a'*64,
        'positionMode':'manual','metadata':{},'snapRelationship':None,
        'transform':{'position':{'x':7,'y':0,'z':0},'quaternion':{'x':0,'y':0,'z':0,'w':1},'scale':1}}]
    doc['routes'] = [{'routeId':'rt-test','label':'Door access','corridorWidth':1,
        'centerline':[{'x':7,'y':0,'z':-2},{'x':7,'y':0,'z':2}],
        'extensions':{'facilityAisle':{'aisleKind':'pedestrian'}}}]
    asset = {'assetId':'asset-test','geometry':{
        'footprintPolygons':[[{'x':-.2,'z':-.2},{'x':.2,'z':-.2},{'x':.2,'z':.2},{'x':-.2,'z':.2}]],
        'heightInterval':{'minimumY':0,'maximumY':1}},'clearances':[]}
    def codes(parameters):
        doc['extensions'][KEY] = compile_perimeter_walls(parameters, doc)
        result = diagnose_layout(doc,[asset],shell=shell_with_plan_boundary({'features':[]},doc))
        return {f['code'] for f in result['findings']}
    assert {'shell_obstacle_collision','aisle_shell_obstructed'} <= codes(settings())
    opened = settings(); opened['openings']=[dict(edge=0,startMeters=5,endMeters=9)]
    assert not {'shell_obstacle_collision','aisle_shell_obstructed'} & codes(opened)


def test_saved_wall_geometry_survives_repository_reload(tmp_path):
    from ai_inspector.facility_layout.repository import FacilityLayoutRepository
    from ai_inspector.facility_layout.authorization import local_facility_principal
    doc = layout(); site = doc['association']['siteId']
    repository = FacilityLayoutRepository(tmp_path)
    principal = local_facility_principal(site_id=site)
    initial = repository.create_layout(principal, site, doc)
    changed = apply_facility_layout_operations(initial['layout'],[
        dict(op='set_perimeter_walls',wallSettings=settings())])['document']
    saved = repository.save_layout(principal,site,doc['layoutId'],changed,initial['revision'])
    loaded = repository.get_layout(principal,site,doc['layoutId'])
    assert saved['revision'] == loaded['revision']
    assert loaded['layout']['extensions'][KEY] == changed['extensions'][KEY]
    validate_perimeter_walls(loaded['layout'])
