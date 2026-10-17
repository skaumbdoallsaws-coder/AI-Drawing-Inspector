"""Add two catalog floor fans to Factory 02, with isolated validation first."""
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
from shapely.geometry import LineString, box
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.add_factory02_dispatch_office import LAYOUT_ID, MANUAL_ID, SITE, STORE, BOUNDS, publish
from tools.audit_independent_factory_layer2 import footprint, marking_polygon, write_json

BASE_REVISION = 'e8433641ed1c870b23aed9bd71c87c762a919f877c8d423aa25a27e3f7ceb9eb'
ASSET_ID = 'asset-floor-fan-white'
PREFIX = 'pl-independent-office-fan-'


def fan_operations(doc, catalog):
    if doc['layoutId'] != LAYOUT_ID or layout_revision(doc) != BASE_REVISION:
        raise ValueError('Factory 02 has changed; review its revision before adding fans.')
    asset = catalog[ASSET_ID]
    if not asset['definition']['readiness']['placementReady']['value']:
        raise ValueError('Floor fan is not placement-ready.')
    ops = []
    for number, z in ((1, 7.8), (2, 14.2)):
        chair = next(p for p in doc['placements'] if p['placementId'] == f'pl-independent-office-{number}-chair')
        target = chair['transform']['position']
        x = 58.8
        # The actual GLB grille and blades face local +X, not +Z.
        yaw = math.atan2(-(target['z'] - z), target['x'] - x)
        ops.append({'op': 'place_asset', 'placement': {
            'placementId': PREFIX + str(number), 'assetId': ASSET_ID,
            'assetDefinitionRevision': asset['assetDefinitionRevision'],
            'transform': {'position': {'x': x, 'y': 0, 'z': z},
                          'quaternion': {'x': 0, 'y': math.sin(yaw / 2), 'z': 0, 'w': math.cos(yaw / 2)},
                          'scale': 1},
            'positionMode': 'manual', 'snapRelationship': None,
            'metadata': {'instanceLabel': f'Dispatch office floor fan {number}',
                         'inputMethod': 'independent-authoring'},
        }})
    return ops


def audit(before, after, catalog):
    added = after['placements'][len(before['placements']):]
    assert len(added) == 2
    assert {p['placementId'] for p in added} == {PREFIX + '1', PREFIX + '2'}
    restored = deepcopy(after)
    restored['placements'] = restored['placements'][:-2]
    restored['updatedAt'] = before['updatedAt']
    assert restored == before, 'Unrelated layout content changed.'
    shapes = [footprint(p, catalog[ASSET_ID]) for p in added]
    assert all(box(*BOUNDS).covers(shape) for shape in shapes)
    existing = [footprint(p, catalog[p['assetId']]) for p in before['placements']]
    equipment_gap = min(shape.distance(other) for shape in shapes for other in existing)
    assert equipment_gap > 0.5
    assert shapes[0].distance(shapes[1]) > 0.5
    corridors = [LineString([(p['x'], p['z']) for p in r['centerline']]).buffer(r['corridorWidth'] / 2)
                 for r in before['routes']]
    route_gap = min(shape.distance(corridor) for shape in shapes for corridor in corridors)
    assert route_gap > 1.0
    assert all(shape.intersection(marking_polygon(m)).area < 1e-8
               for shape in shapes for m in before['floorMarkings'])
    return {'addedPlacements': 2, 'existingPlacementsUnchanged': len(before['placements']),
            'minimumEquipmentGapMeters': equipment_gap, 'minimumRouteGapMeters': route_gap,
            'withinOffice': True, 'allOtherLayoutContentUnchanged': True,
            'limitations': ['Placement only; no airflow, electrical or ventilation-performance qualification.']}


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
        operations = fan_operations(before, catalog)
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
                  'spatialMetrics': spatial['metrics'], 'fanAssetRevision': catalog[ASSET_ID]['assetDefinitionRevision']}
        write_json(args.output / 'report.json', report)
        print(json.dumps(report))
    finally:
        host.close()


if __name__ == '__main__':
    main()
