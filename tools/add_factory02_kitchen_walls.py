"""Enclose Factory 02's kitchen with existing polygon walls and a real entrance.

Dry-run validates an isolated copy. --publish saves only that reviewed candidate
against its unchanged base; the manual reference and other furniture are retained.
"""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from ai_inspector.facility_layout.perimeter_walls import KEY, validate_perimeter_walls
from tools.add_factory02_dispatch_office import LAYOUT_ID, MANUAL_ID, SITE, STORE, publish
from tools.audit_independent_factory_layer2 import footprint, marking_polygon, write_json

BASE_REVISION = '184423d9e8ab181755124cfb81f2447ffda4825e929e9906a65b629b2fcc218f'
KITCHEN_ID = 'pl-independent-cafeteria-kitchen'
ZONE_ID = 'zn-independent-cafeteria-kitchen'
ROUTE_ID = 'rt-independent-kitchen-entrance'
BOUNDS = (53.8, 29.5, 61.0, 36.1)


def kitchen_operations(doc):
    if doc['layoutId'] != LAYOUT_ID or layout_revision(doc) != BASE_REVISION:
        raise ValueError('Factory 02 has changed; review its revision before enclosing the kitchen.')
    if KEY in doc.get('extensions', {}):
        raise ValueError('Existing polygon walls must not be overwritten.')
    kitchen = next(p for p in doc['placements'] if p['placementId'] == KITCHEN_ID)
    if kitchen['assetId'] != 'asset-kitchen-assembly':
        raise ValueError('Expected kitchen assembly is missing.')
    x0, z0, x1, z1 = BOUNDS
    boundary = [dict(x=x0, z=z0), dict(x=x1, z=z0), dict(x=x1, z=z1), dict(x=x0, z=z1)]
    return [
        {'op': 'move_placement', 'placementId': KITCHEN_ID, 'movementKind': 'user',
         'position': {'x': 57.3, 'y': 0, 'z': 32.8}},
        {'op': 'add_zone', 'zone': {
            'zoneId': ZONE_ID, 'label': 'Kitchen', 'zoneType': 'workcell',
            'boundary': deepcopy(boundary), 'floorElevation': 0, 'anchors': [], 'evidence': [],
            'extensions': {'style': {'fillColor': '#b4c8d0'}},
        }},
        {'op': 'set_perimeter_walls', 'wallSettings': {
            'boundarySource': 'polygon', 'boundary': boundary,
            'heightMeters': 2.8, 'thicknessMeters': 0.15,
            'openings': [{'edge': 0, 'startMeters': 2.6, 'endMeters': 4.4}],
        }},
        {'op': 'add_aisle', 'routeId': ROUTE_ID, 'aisle': {
            'label': 'Kitchen Entrance', 'centerline': [
                {'x': 57.3, 'y': 0, 'z': 28.5}, {'x': 57.3, 'y': 0, 'z': 30.3}],
            'corridorWidth': 1.2, 'aisleKind': 'pedestrian', 'direction': 'two_way',
            'color': '#38bdf8', 'clearanceEvidenceStatus': 'unverified',
        }},
    ]


def wall_shape(doc):
    return unary_union([Polygon([(p['x'], p['z']) for p in panel])
                        for panel in doc['extensions'][KEY]['panels']])


def audit(before, after, catalog):
    validate_perimeter_walls(after)
    old_kitchen = next(p for p in before['placements'] if p['placementId'] == KITCHEN_ID)
    restored = deepcopy(after)
    new_kitchen = next(p for p in restored['placements'] if p['placementId'] == KITCHEN_ID)
    assert new_kitchen['transform']['position'] == {'x': 57.3, 'y': 0, 'z': 32.8}
    new_kitchen['transform']['position'] = deepcopy(old_kitchen['transform']['position'])
    restored['zones'] = [z for z in restored['zones'] if z['zoneId'] != ZONE_ID]
    restored['routes'] = [r for r in restored['routes'] if r['routeId'] != ROUTE_ID]
    del restored['extensions'][KEY]
    restored['updatedAt'] = before['updatedAt']
    assert restored == before, 'Unrelated layout content changed.'
    walls = wall_shape(after)
    shapes = {p['placementId']: footprint(p, catalog[p['assetId']]) for p in after['placements']}
    kitchen = shapes[KITCHEN_ID]
    interior = box(*BOUNDS).buffer(-0.075, join_style='mitre')
    assert interior.covers(kitchen)
    parent = next(z for z in before['zones'] if z['zoneId'] == 'zn-independent-cafeteria')
    assert Polygon([(p['x'], p['z']) for p in parent['boundary']]).covers(walls)
    equipment_gap = min(walls.distance(s) for s in shapes.values())
    assert equipment_gap > 0.1
    assert all(walls.intersection(marking_polygon(m)).area < 1e-8 for m in after['floorMarkings'])
    corridors = {r['routeId']: LineString([(p['x'], p['z']) for p in r['centerline']]).buffer(r['corridorWidth'] / 2)
                 for r in after['routes']}
    route_gap = min(walls.distance(s) for s in corridors.values())
    assert route_gap > 0.1
    entrance = corridors[ROUTE_ID]
    assert corridors['rt-independent-cafeteria-walk'].intersects(entrance)
    assert min(entrance.distance(s) for s in shapes.values()) > 0.1
    assert not walls.intersects(box(56.4001, 29.42, 58.1999, 29.58))
    assert walls.intersects(box(55, 29.45, 56, 29.55))
    assert walls.intersects(box(59, 29.45, 60, 29.55))
    assert all(kitchen.distance(s) > 0.1 for pid, s in shapes.items() if pid != KITCHEN_ID)
    return {
        'wallCenterlineBoundsMeters': list(BOUNDS), 'wallHeightMeters': 2.8,
        'wallThicknessMeters': 0.15, 'entranceClearWidthMeters': 1.8,
        'wallPanels': len(after['extensions'][KEY]['panels']),
        'kitchenMovedBackMeters': 0.8, 'minimumWallEquipmentGapMeters': equipment_gap,
        'minimumWallRouteGapMeters': route_gap,
        'frontLandingDepthMeters': kitchen.bounds[1] - (BOUNDS[1] + 0.075),
        'joinsCafeteriaPedestrianAccess': True,
        'unchangedPlacements': len(before['placements']) - 1,
        'allOtherLayoutContentUnchanged': True,
        'limitations': ['Concept enclosure with an open full-height entrance, no door leaf or roof.',
                       'No utility, ventilation, fire, hygiene or accessibility certification.',
                       'Kitchen assembly retains a single footprint; internal circulation is not qualified.'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    args = parser.parse_args()
    if args.publish:
        publish(args.output)
        return
    args.output.mkdir(parents=True, exist_ok=False)
    directory = STORE / 'layouts/local/site-local/layouts'
    before_bytes = (directory / (LAYOUT_ID + '.json')).read_bytes()
    before = json.loads(before_bytes)
    operations = kitchen_operations(before)
    stage = (args.output / 'validation-store').resolve()
    copytree(_native_fs_path(STORE / 'authorities'), _native_fs_path(stage / 'authorities'))
    copytree(_native_fs_path(STORE / 'layouts/local'), _native_fs_path(stage / 'layouts/local'))
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
        candidate = apply_facility_layout_operations(before, operations,
            updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks = audit(before, candidate, catalog)
        principal = host.principal()
        dependencies = host.service.validate_dependencies(principal, SITE, candidate).to_dict()
        spatial = host.service._diagnose_spatial(principal, SITE, candidate)
        routing = host.service._diagnose_routing(principal, SITE, candidate)
        write_json(args.output / 'validation.json', dict(dependencies=dependencies, spatial=spatial, routing=routing))
        host.service._require_spatially_valid(spatial)
        host.service._require_routing_valid(routing)
        saved = host.service.save_layout(principal, SITE, LAYOUT_ID, candidate, layout_revision(before))
        (args.output / 'before.json').write_bytes(before_bytes)
        write_json(args.output / 'candidate.json', saved['layout'])
        write_json(args.output / 'operations.json', operations)
        report = {'status': 'validated', 'baseRevision': layout_revision(before),
                  'candidateRevision': saved['revision'], **checks, 'totalPlacements': len(candidate['placements']),
                  'manualSha256': hashlib.sha256((directory / (MANUAL_ID + '.json')).read_bytes()).hexdigest(),
                  'defaultLayoutId': json.loads((directory / 'registry.json').read_text())['defaultLayoutId'],
                  'spatialMetrics': spatial['metrics']}
        write_json(args.output / 'report.json', report)
        print(json.dumps(report))
    finally:
        host.close()


if __name__ == '__main__':
    main()
