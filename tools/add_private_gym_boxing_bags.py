"""Add two revision-bound copies of the reviewed wall-mounted boxing bag."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
import math
from pathlib import Path
from shutil import copytree
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
if sys.version_info[:2] == (3, 14):
    sys.path.insert(0, str(Path.home() / 'AppData/Roaming/Python/Python314/site-packages'))
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from tools.audit_independent_factory_layer2 import footprint

OUT = ROOT / '.runtime/private-gym-three-bags-20261007'
BAG = 'asset-gym-sports-boxing-bag'


def operations(before):
    bags = [p for p in before['placements'] if p['assetId'] == BAG]
    assert len(bags) == 1, 'Expected the single reviewed bag; do not duplicate an already expanded row'
    original = bags[0]
    relation = original['snapRelationship']
    assert relation['family'] == 'wall_attachment'
    wall = next(p for p in before['placements'] if p['placementId'] == relation['supportPlacementId'])
    q = wall['transform']['quaternion']
    yaw = 2 * math.atan2(q['y'], q['w'])
    result = []
    for number, offset in [(2, -2), (3, 2)]:
        bag = deepcopy(original)
        bag['placementId'] = original['placementId'] + '-' + str(number)
        bag['metadata']['instanceLabel'] = 'Boxing Bag ' + str(number)
        bag['snapRelationship']['localX'] += offset
        position = bag['transform']['position']
        position['x'] += math.cos(yaw) * offset
        position['z'] -= math.sin(yaw) * offset
        result.append(dict(op='place_asset', placement=bag))
    return result


def audit(before, candidate, catalog):
    from shapely.geometry import LineString
    existing = {p['placementId']: p for p in before['placements']}
    current = {p['placementId']: p for p in candidate['placements']}
    assert all(current[key] == value for key, value in existing.items())
    assert len(current) == len(existing) + 2
    for field in before:
        if field not in ('placements', 'updatedAt'):
            assert candidate[field] == before[field], 'Unrelated field changed: ' + field
    bags = [p for p in candidate['placements'] if p['assetId'] == BAG]
    assert len(bags) == 3
    shapes = [footprint(p, catalog[p['assetId']]) for p in bags]
    for i, a in enumerate(bags):
        for j, b in enumerate(bags[i + 1:], i + 1):
            pa, pb = a['transform']['position'], b['transform']['position']
            assert math.hypot(pa['x'] - pb['x'], pa['z'] - pb['z']) >= 2 - 1e-6
            assert not shapes[i].intersects(shapes[j])
    for route in candidate['routes']:
        if route['routeId'].startswith('rt-private-gym-sports-'):
            path = LineString([(p['x'], p['z']) for p in route['centerline']]).buffer(route['corridorWidth'] / 2)
            assert all(path.intersection(shape).area < 1e-6 for shape in shapes), route['routeId']
    return dict(totalBags=3, addedPlacements=2, unchangedPlacements=len(existing),
                centerSpacingMeters=2, authoredWalkwaysClear=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'save'])
    args = parser.parse_args()
    target = STORE / 'layouts/local/site-local/layouts' / (LAYOUT + '.json')
    if args.phase == 'save':
        report = json.loads((OUT / 'report.json').read_text())
        if report['status'] == 'saved':
            assert json.loads(target.read_bytes()) == json.loads((OUT / 'saved.json').read_text())
            print(json.dumps(dict(status='already-saved', checks=report['checks'])))
            return
        assert target.read_bytes() == (OUT / 'before.json').read_bytes(), 'Saved gym changed during review'
        native = json.loads((OUT / 'native-check.json').read_text())
        raw = (OUT / 'candidate.json').read_bytes()
        assert native['status'] == 'preview-verified'
        assert native['candidateHash'] == hashlib.sha256(raw).hexdigest()
        host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
        try:
            receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, json.loads(raw), report['baseRevision'])
        finally:
            host.close()
        write(OUT / 'saved.json', receipt['layout'])
        after = saved_hashes()
        assert all(after[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name, 'registry.json'))
        report.update(status='saved', savedRevision=receipt['revision'], otherLayoutsUnchanged=True)
        write(OUT / 'report.json', report)
        print(json.dumps(dict(status='saved', checks=report['checks'])))
        return

    OUT.mkdir(parents=True, exist_ok=True)
    raw = target.read_bytes()
    before = json.loads(raw)
    snapshot = OUT / 'before.json'
    if snapshot.exists():
        assert snapshot.read_bytes() == raw, 'Base changed'
    else:
        snapshot.write_bytes(raw)
    staged = OUT / 'validation-store'
    for rel in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE / rel), _native_fs_path(staged / rel), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(staged, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
        ops = operations(before)
        candidate = apply_facility_layout_operations(before, ops, updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks = audit(before, candidate, catalog)
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT / 'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
    finally:
        host.close()
    write(OUT / 'candidate.json', receipt['layout'])
    write(OUT / 'operations.json', ops)
    write(OUT / 'report.json', dict(status='validated', baseRevision=layout_revision(before), checks=checks, layoutHashes=saved_hashes()))
    profile = json.loads((ROOT / '.runtime/private-gym-sports-20261007/profile.json').read_text())
    profile.update(profileId='private-gym-three-bags', origin='http://127.0.0.1:8543', dataRoot=str(OUT), backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()))
    write(OUT / 'profile.json', profile)
    shot = dict(name='01-three-bags', position=dict(x=75.2, y=2.5, z=5), target=dict(x=81, y=1.4, z=5), thresholds=dict(detail=1000))
    write(OUT / 'review-config.json', dict(profileId=profile['profileId'], requiredAssets=[BAG], shots=[shot], finalShot=dict(shot, name='02-saved-three-bags')))
    print(json.dumps(dict(status='validated', checks=checks)))


if __name__ == '__main__':
    main()
