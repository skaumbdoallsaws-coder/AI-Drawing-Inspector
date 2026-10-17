"""Stage the remaining Factory 02 annex as a revision-guarded parking concept."""
from copy import deepcopy
import argparse
import json
import math
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shapely.geometry import LineString, box
from shapely.ops import unary_union
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations, MAX_OPERATION_BATCH
from tools.add_factory02_parking_office import boundary, hashes, write_json, verify_native_candidate, CAR_IDS
from tools.audit_independent_factory_layer2 import footprint, marking_polygon
from tools.expand_factory02_lunchroom import rectangle_tiles

STORE = ROOT / '.runtime/facility-layout'
LAYOUT = 'fl-independent-factory-20260928'
RELATIVE = Path('layouts/local/site-local/layouts') / (LAYOUT + '.json')
PREFIX = 'pl-employee-parking-'
STOP = 'asset-factory02-parking-wheel-stop'
NORTH = (334, 30, 376, 96)
SOUTH = (300.1, 96, 376, 200)
WHITE = '#eaf0f2'
YELLOW = '#efca43'


def stalls():
    result = []
    rows = [(343, z, 9, sign) for base in (32, 52, 72)
            for z, sign in ((base + 2.9, -1), (base + 15.7, 1))]
    rows += [(312, z, 20, sign) for base in (107.2, 127.2, 147.2, 167.2)
             for z, sign in ((base + 2.9, -1), (base + 15.7, 1))]
    for row, (start, z, count, sign) in enumerate(rows):
        for column in range(count):
            n = len(result) + 1
            result.append(dict(number=n, row=chr(65 + row), x=start + (column + .5) * 2.8,
                               z=z, width=2.8, depth=5.8, head=sign, occupied=n % 3 != 0))
    return result


def drives():
    return [box(336, 30, 343, 107), box(368.2, 30, 376, 199),
            box(305, 100, 312, 197), box(305, 100, 376, 107), box(305, 190, 376, 197)] + [
                box(336, z, 376, z + 7) for z in (37.8, 57.8, 77.8)] + [
                box(305, z, 376, z + 7) for z in (113, 133, 153, 173)]


def walks():
    return [('amenity-spine', [(335, 27.4), (335, 98)], 1.8),
            ('gym-link', [(331, 84), (335, 84)], 1.8),
            ('conference-link', [(331, 62.5), (335, 62.5)], 1.8),
            ('factory-link', [(297, 98), (335, 98)], 2.4),
            ('factory-sidewalk', [(303, 98), (303, 197)], 2)] + [
                ('north-crossing-' + str(i), [(335, z), (345, z)], 1.8)
                for i, z in enumerate((41.3, 61.3, 81.3))] + [
                ('south-crossing-' + str(i), [(303, z), (315, z)], 1.8)
                for i, z in enumerate((116.5, 136.5, 156.5, 176.5))]


def walk_segments():
    return [LineString([a, b]).buffer(w / 2, cap_style=2)
            for _, points, w in walks() for a, b in zip(points, points[1:])]


def floor_surfaces():
    islands = [('north-island-' + str(i), (343, z, 368.2, z + 1.4), '#74856f')
               for i, z in enumerate((50.6, 70.6, 90.6))]
    islands += [('south-island-' + str(i), (312, z, 368, z + 1.4), '#74856f')
                for i, z in enumerate((125.8, 145.8, 165.8))]
    islands += [('south-end-island', (312, 185.8, 368, 190), '#74856f')]
    return [('asphalt-north', NORTH, '#39444a'), ('asphalt-south', SOUTH, '#39444a'),
            ('west-verge', (300.1, 100, 302, 200), '#74856f'),
            ('west-shoulder', (302, 100, 305, 200), '#bdcbd0'),
            ('entry-plaza', (300.1, 96, 336, 100), '#bdcbd0')] + islands


def operations(catalog):
    ops = []

    def paint(key, kind, x, z, w, d, color=WHITE, text='', rotation=0, y=.008, role='decorative'):
        ops.append(dict(op='add_floor_marking', floorMarking=dict(
            markingId='fm-employee-parking-' + key, markingType=kind, label=key.replace('-', ' ').title(),
            semanticRole=role, transform=dict(position=dict(x=x, y=y, z=z), rotationDegrees=rotation),
            width=w, depth=d, fillColor=color, strokeColor=color, opacity=1, text=text,
            positionMode='manual', metadata=dict(authoredIn='employee_parking_extension'), evidence=[])))

    def place(key, aid, x, z, yaw=0):
        asset = catalog[aid]
        half = math.radians(yaw) / 2
        p = dict(placementId=PREFIX + key, assetId=aid, assetDefinitionRevision=asset['assetDefinitionRevision'],
                 transform=dict(position=dict(x=x, y=0, z=z), quaternion=dict(x=0, y=math.sin(half), z=0, w=math.cos(half)), scale=1),
                 positionMode='manual', snapRelationship=None,
                 metadata=dict(instanceLabel=key.replace('-', ' ').title(), inputMethod='independent-authoring'))
        if aid == STOP:
            p['appearance'] = dict(color=YELLOW)
        ops.append(dict(op='place_asset', placement=p))

    for key, b, title in [('north', NORTH, 'Employee Parking North - 54 Spaces'),
                          ('south', SOUTH, 'Employee Parking South - 160 Spaces')]:
        ops.append(dict(op='add_zone', zone=dict(zoneId='zn-employee-parking-' + key, label=title,
            zoneType='workcell', boundary=boundary(b), floorElevation=0, anchors=[], evidence=[],
            extensions=dict(style=dict(fillColor='#526069')))))

    surfaces = floor_surfaces()
    for index, (key, bounds, color) in enumerate(surfaces):
        exclude = walk_segments() + [box(*s[1]) for s in surfaces[index + 1:]]
        for tile, (x0, z0, x1, z1) in enumerate(rectangle_tiles(bounds, exclude)):
            paint('surface-' + key + '-' + str(tile), 'solid_line', (x0 + x1) / 2, (z0 + z1) / 2,
                  x1 - x0, z1 - z0, color, y=0)

    for s in stalls():
        n, x, z, head = s['number'], s['x'], s['z'], s['head']
        key = f'{n:03}'
        paint('bay-' + key, 'parking_box', x, z, s['width'], s['depth'], role='parking')
        paint('number-' + key, 'floor_text', x, z - head * 3.3, 1.3, .45, text='E' + key)
        place('wheel-stop-' + key, STOP, x, z + head * 2.68)
        if s['occupied']:
            place('car-' + key, CAR_IDS[(n // 3 + n) % 2], x, z, 180 if head == -1 else 0)

    for key, points, width in walks():
        ops.append(dict(op='add_aisle', routeId='rt-employee-parking-' + key, aisle=dict(
            label=key.replace('-', ' ').title(), centerline=[dict(x=x, y=0, z=z) for x, z in points],
            corridorWidth=width, aisleKind='pedestrian', direction='two_way', color='#62becb',
            clearanceEvidenceStatus='unverified')))

    for i, z in enumerate((41.3, 61.3, 81.3)):
        paint('north-crosswalk-' + str(i), 'crosswalk', 339.5, z, 7, 1.8, rotation=0, role='pedestrian_lane')
    for i, z in enumerate((116.5, 136.5, 156.5, 176.5)):
        paint('south-crosswalk-' + str(i), 'crosswalk', 308.5, z, 7, 1.8, role='pedestrian_lane')

    # These are parking circulation markings, not authoritative process transfers.
    for i, (x0, x1, z) in enumerate([(343, 368.2, z) for z in (41.3, 61.3, 81.3)] +
                                   [(312, 368, z) for z in (116.5, 136.5, 156.5, 176.5)]):
        paint('aisle-center-' + str(i), 'dashed_line', (x0 + x1) / 2, z, .12, x1 - x0 - 2, YELLOW, rotation=90)
        for direction, offset, yaw in [('east', -1.7, 90), ('west', 1.7, -90)]:
            for j in range(2):
                x = x0 + (x1 - x0) * (j + 1) / 3
                paint(f'aisle-arrow-{i}-{direction}-{j}', 'direction_arrow', x, z + offset, .8, 1.8, rotation=yaw)
    for x, z0, z1 in [(372, 31, 199), (308.5, 108, 190), (339.5, 31, 98)]:
        # Break centerlines at intersections to keep junctions visually legible.
        junctions = (37.8, 57.8, 77.8, 100, 113, 133, 153, 173, 190)
        sections = rectangle_tiles((x - .06, z0, x + .06, z1), [box(x - 5, z, x + 5, z + 7) for z in junctions])
        for i, (a, b, c, d) in enumerate(sections):
            paint(f'spine-center-{x}-{i}', 'dashed_line', x, (b + d) / 2, .12, d - b, YELLOW)
        for i, z in enumerate(range(math.ceil(z0 + 4), int(z1 - 3), 20)):
            paint(f'spine-down-{x}-{i}', 'direction_arrow', x - 1.7, z, .8, 1.8, rotation=0)
            paint(f'spine-up-{x}-{i}', 'direction_arrow', x + 1.7, z, .8, 1.8, rotation=180)
    for key, z in [('main', 103.5), ('south', 193.5)]:
        paint('entry-center-' + key, 'dashed_line', 339, z, .12, 58, YELLOW, rotation=90)
        paint('entry-in-' + key, 'direction_arrow', 373, z + 1.7, .9, 2, rotation=-90)
        paint('entry-out-' + key, 'direction_arrow', 373, z - 1.7, .9, 2, rotation=90)
        paint('entry-label-' + key, 'floor_text', 365, z + 1.7, 6, .65, text='EMPLOYEE ENTRY')
    paint('title', 'floor_text', 339, 188, 28, 1.2, text='INSPECTORPRO | EMPLOYEE PARKING')
    paint('factory-plaza', 'floor_text', 315, 96.4, 13, .6, '#36535c', text='FACTORY / STAFF ACCESS')
    return ops


def apply_batches(before, ops):
    candidate = deepcopy(before)
    for start in range(0, len(ops), MAX_OPERATION_BATCH):
        candidate = apply_facility_layout_operations(candidate, ops[start:start + MAX_OPERATION_BATCH],
                                                     base_revision=layout_revision(candidate))['document']
    return candidate


def audit(before, after, catalog):
    restored = deepcopy(after)
    for field, key, prefix in [('placements', 'placementId', PREFIX), ('zones', 'zoneId', 'zn-employee-parking-'),
        ('routes', 'routeId', 'rt-employee-parking-'), ('floorMarkings', 'markingId', 'fm-employee-parking-')]:
        restored[field] = [p for p in after[field] if not p[key].startswith(prefix)]
    restored['updatedAt'] = before['updatedAt']
    assert restored == before, 'Existing layout content changed'
    added = [p for p in after['placements'] if p['placementId'].startswith(PREFIX)]
    expected_ids = {PREFIX + f"wheel-stop-{s['number']:03}" for s in stalls()} | {
        PREFIX + f"car-{s['number']:03}" for s in stalls() if s['occupied']}
    assert {p['placementId'] for p in added} == expected_ids, 'Missing or unexpected parking placement'
    assert all(p['transform']['scale'] == 1 and 'zoneId' not in p for p in added), 'Noncanonical placement'
    shapes = {p['placementId']: footprint(p, catalog[p['assetId']]) for p in after['placements']}
    bounds = {key: shape.bounds for key, shape in shapes.items()}
    by_id = {p['placementId']: p for p in added}
    drive = unary_union(drives())
    walk = unary_union(walk_segments())
    area = unary_union([box(*NORTH), box(*SOUTH)])
    assert drive.geom_type == 'Polygon' and walk.geom_type == 'Polygon', 'Disconnected circulation'
    for s in stalls():
        bay = box(s['x'] - 1.4, s['z'] - 2.9, s['x'] + 1.4, s['z'] + 2.9)
        assert area.buffer(1e-7).covers(bay), 'Bay outside lot'
        assert bay.intersection(drive).area < 1e-7, 'Bay blocks vehicle circulation'
        front = LineString([(s['x'] - 1.4, s['z'] - s['head'] * 2.9),
                            (s['x'] + 1.4, s['z'] - s['head'] * 2.9)])
        assert drive.buffer(1e-7).covers(front), 'Bay has no direct drive-aisle access'
        if s['occupied']:
            key = PREFIX + f"car-{s['number']:03}"
            assert by_id[key]['assetId'] in CAR_IDS, 'Wrong vehicle model'
            assert bay.covers(shapes[key]) and shapes[key].distance(bay.boundary) > .2, 'Car does not fit its bay'
    for p in added:
        shape = shapes[p['placementId']]
        assert area.covers(shape), 'Placement outside new lot'
        assert shape.intersection(drive).area < 1e-7, 'Blocked drive aisle'
        assert shape.intersection(walk).area < 1e-7, 'Blocked pedestrian connection'
        for other in after['placements']:
            if other['placementId'] != p['placementId']:
                a, b = bounds[p['placementId']], bounds[other['placementId']]
                if a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1]:
                    continue
                assert shape.intersection(shapes[other['placementId']]).area < 1e-7, ('Overlap', p['placementId'], other['placementId'])
    for p in before['placements']:
        assert shapes[p['placementId']].intersection(walk).area < 1e-7, ('Existing obstacle blocks new walk', p['placementId'])
    ground = [marking_polygon(m) for m in after['floorMarkings'] if m['markingId'].startswith('fm-employee-parking-surface-')]
    coverage = unary_union(ground)
    assert abs(sum(s.area for s in ground) - coverage.area) < 1e-7, 'Overlapping ground paint'
    assert coverage.symmetric_difference(area.difference(walk)).area < 1e-6, 'Ground paint has holes'
    markings = {m['markingId']: m for m in after['floorMarkings'] if m['markingId'].startswith('fm-employee-parking-bay-')}
    assert len(markings) == len(stalls()), 'Missing bay outlines'
    for s in stalls():
        m = markings[f"fm-employee-parking-bay-{s['number']:03}"]
        assert m['markingType'] == 'parking_box' and m['semanticRole'] == 'parking'
        assert marking_polygon(m).symmetric_difference(box(s['x'] - 1.4, s['z'] - 2.9, s['x'] + 1.4, s['z'] + 2.9)).area < 1e-7
    routes = {r['routeId']: r for r in after['routes'] if r['routeId'].startswith('rt-employee-parking-')}
    assert len(routes) == len(walks()), 'Missing pedestrian links'
    for key, points, width in walks():
        r = routes['rt-employee-parking-' + key]
        assert r['centerline'] == [dict(x=x, y=0, z=z) for x, z in points] and r['corridorWidth'] == width
    return dict(newSpaces=len(stalls()),occupiedSpaces=sum(s['occupied'] for s in stalls()),
        totalSpacesWithExisting=234,existingPlacementsPreserved=len(before['placements']),
        vehicleCirculationConnected=True,pedestrianConnectionsClear=True,
        bayWidthMeters=2.8,bayDepthMeters=5.8,parkingAisleWidthMeters=7,
        engineeringApproval=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--native-report', type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    target, manifest = STORE / RELATIVE, ROOT / PRIVATE_ASSET_MANIFEST
    if args.publish:
        report = json.loads((out / 'report.json').read_text())
        assert report['status'] == 'validated' and args.native_report
        assert target.read_bytes() == (out / 'before.json').read_bytes(), 'Factory 02 changed'
        assert hashes(target.parent) == report['layoutHashes'], 'Saved layouts changed'
        assert manifest.read_bytes() == (out / 'catalog-before.json').read_bytes(), 'Catalog changed'
        candidate = json.loads((out / 'candidate.json').read_text())
        verify_native_candidate(json.loads(args.native_report.read_text()), candidate, (out / 'validation-store' / RELATIVE).read_bytes())
        host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
        try:
            audit(json.loads((out / 'before.json').read_text()), candidate, {a['assetId']: a for a in host.authoritative_asset_catalog()})
            saved = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
        finally:
            host.close()
        others = lambda values: {k: v for k, v in values.items() if k != target.name}
        assert others(hashes(target.parent)) == others(report['layoutHashes'])
        write_json(out / 'saved.json', saved['layout'])
        report.update(status='saved', savedRevision=saved['revision'], otherLayoutsUnchanged=True)
    else:
        raw = target.read_bytes()
        before = json.loads(raw)
        assert not any(p['placementId'].startswith(PREFIX) for p in before['placements'])
        out.mkdir(parents=True, exist_ok=False)
        (out / 'before.json').write_bytes(raw)
        (out / 'catalog-before.json').write_bytes(manifest.read_bytes())
        stage = out / 'validation-store'
        copytree(_native_fs_path(STORE / 'authorities'), _native_fs_path(stage / 'authorities'))
        copytree(_native_fs_path(STORE / 'layouts/local'), _native_fs_path(stage / 'layouts/local'))
        host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=ROOT)
        try:
            catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
            ops = operations(catalog)
            candidate = apply_batches(before, ops)
            checks = audit(before, candidate, catalog)
            spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
            write_json(out / 'spatial.json', spatial)
            host.service._require_spatially_valid(spatial)
            assert not any(f['code'] in {'aisle_obstructed', 'placement_collision', 'zone_containment_violation', 'placement_outside_floor'}
                and any(s.startswith((PREFIX, 'rt-employee-parking-')) for s in f['subjectRefs'])
                for f in spatial['findings']), 'New parking spatial warning'
            base = layout_revision(before)
            saved = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, base)
            write_json(out / 'candidate.json', saved['layout'])
            write_json(out / 'operations.json', ops)
            write_json(out / 'stalls.json', stalls())
            report = dict(status='validated', baseRevision=base, candidateRevision=saved['revision'], checks=checks,
                layoutHashes=hashes(target.parent), placementCount=len(candidate['placements']), operationCount=len(ops),
                limitations=['Concept layout only: turning envelopes, traffic, accessibility, drainage and code compliance require separate review.'])
        finally:
            host.close()
    write_json(out / 'report.json', report)
    print(json.dumps({k: report[k] for k in ('status', 'placementCount', 'checks')}))


if __name__ == '__main__':
    main()
