"""Author and validate a photo-inspired cafeteria in Factory 02.

This guarded one-layout authoring tool reuses the operation kernel and Save.
It is not a new Sage capability or a food-service installation qualification.
"""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shapely.geometry import LineString, Polygon, box
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.add_factory02_dispatch_office import LAYOUT_ID, MANUAL_ID, SITE, STORE, publish
from tools.audit_independent_factory_layer2 import footprint, marking_polygon, write_json

BASE_REVISION = '247b9723ef009d5788ce6717e7d5df635fd70b899b477f8ccf564e5ccacf3f7c'
ZONE_ID = 'zn-independent-cafeteria'
ROUTE_ID = 'rt-independent-cafeteria-walk'
PREFIX = 'pl-independent-cafeteria-'
TABLE = 'asset-5589t51-round-plastic-folding-table'
CHAIR = 'asset-chair-black'
KITCHEN = 'asset-kitchen-assembly'
ASSET_IDS = (TABLE, CHAIR, KITCHEN)
BOUNDS = (53.5, 17.0, 63.0, 36.5)
TABLE_CENTERS = ((55.3, 20.2), (59.2, 20.2), (55.3, 25.0), (59.2, 25.0))


def cafeteria_operations(doc, catalog):
    if doc['layoutId'] != LAYOUT_ID or layout_revision(doc) != BASE_REVISION:
        raise ValueError('Factory 02 has changed; review its revision before adding the cafeteria.')
    for aid in ASSET_IDS:
        if not catalog[aid]['definition']['readiness']['placementReady']['value']:
            raise ValueError('Cafeteria asset is not placement-ready: ' + aid)
    x0, z0, x1, z1 = BOUNDS
    ops = [{'op': 'add_zone', 'zone': {
        'zoneId': ZONE_ID, 'label': 'Cafeteria + Kitchen', 'zoneType': 'workcell',
        'boundary': [{'x': x0, 'z': z0}, {'x': x1, 'z': z0},
                     {'x': x1, 'z': z1}, {'x': x0, 'z': z1}],
        'floorElevation': 0, 'anchors': [], 'evidence': [],
        'extensions': {'style': {'fillColor': '#92b8a0'}},
    }}]

    def place(key, aid, x, z, label, yaw=0):
        ops.append({'op': 'place_asset', 'placement': {
            'placementId': PREFIX + key, 'assetId': aid,
            'assetDefinitionRevision': catalog[aid]['assetDefinitionRevision'],
            'transform': {'position': {'x': x, 'y': 0, 'z': z},
                          'quaternion': {'x': 0, 'y': math.sin(yaw / 2),
                                         'z': 0, 'w': math.cos(yaw / 2)}, 'scale': 1},
            'positionMode': 'manual', 'snapRelationship': None,
            'metadata': {'instanceLabel': label, 'inputMethod': 'independent-authoring'},
        }})

    for number, (x, z) in enumerate(TABLE_CENTERS, 1):
        place(f'table-{number}', TABLE, x, z, f'Cafeteria table {number}')
        for side, (dx, dz) in enumerate(((0, -1.15), (1.15, 0), (0, 1.15), (-1.15, 0)), 1):
            # Chair back is local -Z, so local +Z must face the table center.
            yaw = math.atan2(-dx, -dz)
            place(f'table-{number}-chair-{side}', CHAIR, x + dx, z + dz,
                  f'Cafeteria table {number} chair {side}', yaw)
    # The source kitchen's tall units are on -X and its island/stools on +X.
    # +90 degrees faces that serving side toward the seating at lower world Z.
    place('kitchen', KITCHEN, 57.3, 32.0, 'Cafeteria kitchen and serving island', math.pi / 2)
    ops.append({'op': 'add_aisle', 'routeId': ROUTE_ID, 'aisle': {
        'label': 'Cafeteria Pedestrian Access',
        'centerline': [{'x': 54.1, 'y': 0, 'z': 28.5}, {'x': 62, 'y': 0, 'z': 28.5}],
        'corridorWidth': 1.5, 'aisleKind': 'pedestrian', 'direction': 'two_way',
        'color': '#38bdf8', 'clearanceEvidenceStatus': 'unverified',
    }})
    return ops


def audit(before, after, catalog):
    added = [p for p in after['placements'] if p['placementId'].startswith(PREFIX)]
    assert len(added) == 21
    restored = deepcopy(after)
    restored['placements'] = [p for p in restored['placements'] if not p['placementId'].startswith(PREFIX)]
    restored['zones'] = [z for z in restored['zones'] if z['zoneId'] != ZONE_ID]
    restored['routes'] = [r for r in restored['routes'] if r['routeId'] != ROUTE_ID]
    restored['updatedAt'] = before['updatedAt']
    assert restored == before, 'Unrelated layout content changed.'
    zone = box(*BOUNDS)
    parent = next(z for z in before['zones'] if z['zoneId'] == 'zn-independent-dispatch')
    assert Polygon([(p['x'], p['z']) for p in parent['boundary']]).covers(zone)
    old_shapes = [footprint(p, catalog[p['assetId']]) for p in before['placements']]
    new_shapes = [footprint(p, catalog[p['assetId']]) for p in added]
    assert all(zone.covers(shape) for shape in new_shapes)
    assert all(zone.intersection(shape).area < 1e-8 for shape in old_shapes)
    assert all(zone.intersection(marking_polygon(m)).area < 1e-8 for m in before['floorMarkings'])
    assert all(shape.distance(other) > 0.05 for i, shape in enumerate(new_shapes)
               for other in new_shapes[i + 1:]), 'Cafeteria furniture overlaps.'
    existing_gap = min(shape.distance(other) for shape in new_shapes for other in old_shapes)
    assert existing_gap > 1.0
    corridors = [LineString([(p['x'], p['z']) for p in r['centerline']]).buffer(r['corridorWidth'] / 2)
                 for r in after['routes']]
    route_gap = min(shape.distance(corridor) for shape in new_shapes for corridor in corridors)
    assert route_gap > 0.5
    access = after['routes'][-1]
    access_shape = LineString([(p['x'], p['z']) for p in access['centerline']]).buffer(0.75)
    assert all(access_shape.distance(shape) > 0 for shape in old_shapes)
    office_walk = next(r for r in before['routes'] if r['routeId'] == 'rt-independent-dispatch-office-walk')
    assert access_shape.intersects(LineString([(p['x'], p['z']) for p in office_walk['centerline']]))
    return {'addedPlacements': 21, 'tables': 4, 'chairs': 16, 'kitchenAssemblies': 1,
            'existingPlacementsUnchanged': len(before['placements']), 'cafeteriaBounds': list(BOUNDS),
            'minimumExistingEquipmentGapMeters': existing_gap, 'minimumRouteGapMeters': route_gap,
            'pedestrianAccessWidthMeters': 1.5, 'joinsOfficePedestrianAccess': True,
            'allOtherLayoutContentUnchanged': True,
            'limitations': ['Open-plan furnishing concept, not an enclosed food-service room.',
                           'Kitchen includes its original island and three stools as one assembly.',
                           'No utility connections, exhaust, hygiene, fire, accessibility or seating-capacity certification.']}


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
    stage = (args.output / 'validation-store').resolve()
    copytree(_native_fs_path(STORE / 'authorities'), _native_fs_path(stage / 'authorities'))
    copytree(_native_fs_path(STORE / 'layouts/local'), _native_fs_path(stage / 'layouts/local'))
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
        operations = cafeteria_operations(before, catalog)
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
                  'spatialMetrics': spatial['metrics'],
                  'assetRevisions': {aid: catalog[aid]['assetDefinitionRevision'] for aid in ASSET_IDS}}
        write_json(args.output / 'report.json', report)
        print(json.dumps(report))
    finally:
        host.close()


if __name__ == '__main__':
    main()
