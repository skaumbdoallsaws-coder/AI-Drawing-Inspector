"""Install the four visually accepted concept cars using measured assets and guarded Save."""
from collections import Counter
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from shapely.geometry import box
from ai_inspector.facility_layout.authority_repository import _native_fs_path, RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.add_factory02_employee_parking import STORE, LAYOUT, RELATIVE, stalls, drives, walk_segments
from tools.add_factory02_parking_office import hashes, write_json, verify_native_candidate
from tools.audit_independent_factory_layer2 import footprint

IMPORT = ROOT / '.runtime/car-collection-20261003'
NUMBERS = (1, 5, 10, 14)
IMPORTED_ASSETS = tuple('asset-vehicle-collection-' + key for key in ('concept', 'roadster', 'temerario'))
ASSETS = IMPORTED_ASSETS[:1]
REJECTED_ASSETS = IMPORTED_ASSETS[1:]
REPLACEMENTS = {f'pl-employee-parking-car-{n:03}': ASSETS[0] for n in NUMBERS}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def operations(before, catalog):
    placements = {p['placementId']: p for p in before['placements']}
    ops = []
    for pid, aid in REPLACEMENTS.items():
        original = placements[pid]
        assert original['assetId'] in ('asset-import-car-93', 'asset-import-tesla-roadster'), 'Unexpected original car'
        assert original['positionMode'] == 'manual' and not original['snapRelationship']
        replacement = deepcopy(original)
        replacement.update(assetId=aid, assetDefinitionRevision=catalog[aid]['assetDefinitionRevision'])
        replacement['metadata']['instanceLabel'] = catalog[aid]['displayName'] + ' - E' + pid[-3:]
        ops.extend([dict(op='delete_placement', placementId=pid), dict(op='place_asset', placement=replacement)])
    return ops


def audit(before, after, catalog):
    old = {p['placementId']: p for p in before['placements']}
    new = {p['placementId']: p for p in after['placements']}
    assert len(new) == len(after['placements']) == len(before['placements']) and set(new) == set(old)
    restored = deepcopy(after)
    restored['placements'] = deepcopy(before['placements'])
    restored['updatedAt'] = before['updatedAt']
    assert restored == before, 'Non-placement content changed'
    expected_ops = operations(before, catalog)
    expected = {op['placement']['placementId']: op['placement'] for op in expected_ops if op['op'] == 'place_asset'}
    for pid, p in new.items():
        assert p == expected.get(pid, old[pid]), ('Unapproved placement change', pid)
    bays = {s['number']: s for s in stalls()}
    shapes = {pid: footprint(p, catalog[p['assetId']]) for pid, p in new.items()}
    clear = drives() + walk_segments()
    margins = []
    for pid, aid in REPLACEMENTS.items():
        p = new[pid]
        assert p['assetId'] == aid and p['transform']['scale'] == 1 and p['transform']['position']['y'] == 0
        aabb = catalog[aid]['definition']['geometry']['aabb']
        dims = {label: aabb['maximum'][axis] - aabb['minimum'][axis]
                for label, axis in (('width', 'x'), ('height', 'y'), ('depth', 'z'))}
        assert 4.5 < dims['depth'] < 5 and 1.8 < dims['width'] < 2.3 and 1 < dims['height'] < 1.6
        s = bays[int(pid[-3:])]
        bay = box(s['x'] - 1.4, s['z'] - 2.9, s['x'] + 1.4, s['z'] + 2.9)
        assert bay.covers(shapes[pid].buffer(.2, join_style=2)), ('Bay margin', pid)
        margins.append((2.8 - dims['width']) / 2)
        for region in clear:
            assert shapes[pid].intersection(region).area < 1e-7, ('Blocked circulation', pid)
        for other, shape in shapes.items():
            if other != pid:
                assert shapes[pid].intersection(shape).area < 1e-7, ('Placement overlap', pid, other)
    counts = Counter(new[pid]['assetId'] for pid in REPLACEMENTS)
    assert dict(counts) == {aid: 4 for aid in ASSETS}
    assert not any(p['assetId'] in REJECTED_ASSETS for p in after['placements'])
    return dict(replacedCars=len(REPLACEMENTS), modelCounts=dict(counts), remainingPlacementsUnchanged=len(old)-len(REPLACEMENTS),
                minimumSideMarginMeters=min(margins), scale=1, officeParkingUnchanged=True,
                markingsAndCirculationUnchanged=True)


def asset_files(entries):
    result = {}
    for a in entries:
        folder = (ROOT / a['artifact']).parent
        assert a['measuredGeometry']['method'] == 'full_resolution_transformed_vertices'
        assert sha(folder / a['source']['fileName']) == a['source']['sha256']
        assert sha(Path(r'C:/Users/might/Downloads/cars') / a['source']['fileName']) == a['source']['sha256']
        assert sha(folder / 'model.glb') == a['measuredGeometry']['sourceSha256']
        thumb = json.loads((folder / 'thumbnail-evidence.json').read_text())
        assert thumb['passed'] and thumb['source']['sha256'] == sha(ROOT / a['artifact'])
        for name in (a['source']['fileName'], 'model.glb', 'model-display.glb', 'thumbnail.webp',
                     'thumbnail-evidence.json', 'display-mesh-evidence.json', 'catalog-entry.json'):
            path = folder / name
            result[path.relative_to(ROOT).as_posix()] = sha(path)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--publish-assets', action='store_true')
    parser.add_argument('--publish-layout', action='store_true')
    parser.add_argument('--native-report', type=Path)
    args = parser.parse_args()
    out, target, manifest = args.output.resolve(), STORE / RELATIVE, ROOT / PRIVATE_ASSET_MANIFEST
    entries = json.loads((IMPORT / 'entries.json').read_text())
    assert {a['assetId'] for a in entries} == set(IMPORTED_ASSETS)
    files = asset_files(entries)
    if args.publish_assets or args.publish_layout:
        report = json.loads((out / 'report.json').read_text())
        assert hashes(target.parent) == report['layoutHashes'], 'Saved layout changed'
        assert target.read_bytes() == (out / 'before.json').read_bytes()
        assert files == report['assetFiles'], 'Prepared asset changed'
        staged = out / 'staged-project' / PRIVATE_ASSET_MANIFEST
        if args.publish_assets:
            assert report['status'] == 'validated' and manifest.read_bytes() == (out / 'catalog-before.json').read_bytes()
            RevisionedAuthorityRepository._atomic_write(manifest, staged.read_bytes())
            report['status'] = 'assets-published'
        else:
            assert report['status'] == 'assets-published' and args.native_report
            assert manifest.read_bytes() == staged.read_bytes()
            candidate = json.loads((out / 'candidate.json').read_text())
            verify_native_candidate(json.loads(args.native_report.read_text()), candidate, (out / 'validation-store' / RELATIVE).read_bytes())
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                audit(json.loads((out / 'before.json').read_text()), candidate, {a['assetId']: a for a in host.authoritative_asset_catalog()})
                saved = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
            finally:
                host.close()
            other = lambda values: {k: v for k, v in values.items() if k != target.name}
            assert other(hashes(target.parent)) == other(report['layoutHashes'])
            audit(json.loads((out / 'before.json').read_text()), saved['layout'], json.loads((out / 'catalog-authority.json').read_text()))
            assert json.loads(target.read_text()) == saved['layout']
            write_json(out / 'saved.json', saved['layout'])
            report.update(status='saved', savedRevision=saved['revision'], otherLayoutsUnchanged=True)
    else:
        out.mkdir(parents=True, exist_ok=False)
        (out / 'before.json').write_bytes(target.read_bytes())
        (out / 'catalog-before.json').write_bytes(manifest.read_bytes())
        before = json.loads(target.read_text())
        library = json.loads(manifest.read_text())
        existing = {a['assetId']: a for a in library['assets']}
        for entry in entries:
            if entry['assetId'] in existing:
                assert existing[entry['assetId']] == entry, 'Imported library entry changed'
        # The user rejected the chopped Roadster/Temerario visuals. Keep their
        # originals and diagnostics on disk, but do not offer them for placement.
        library['assets'] = [a for a in library['assets'] if a['assetId'] not in REJECTED_ASSETS]
        library['assets'].extend(a for a in entries if a['assetId'] in ASSETS and a['assetId'] not in existing)
        library['summary']['total'] = len(library['assets'])
        write_json(out / 'staged-project' / PRIVATE_ASSET_MANIFEST, library)
        stage = out / 'validation-store'
        copytree(_native_fs_path(STORE / 'authorities'), _native_fs_path(stage / 'authorities'))
        copytree(_native_fs_path(STORE / 'layouts/local'), _native_fs_path(stage / 'layouts/local'))
        host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=out / 'staged-project')
        try:
            catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
            write_json(out / 'catalog-authority.json', catalog)
            base = layout_revision(before)
            ops = operations(before, catalog)
            candidate = apply_facility_layout_operations(before, ops, base_revision=base)['document']
            checks = audit(before, candidate, catalog)
            spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
            write_json(out / 'spatial.json', spatial)
            host.service._require_spatially_valid(spatial)
            assert not any(f['code'] in {'aisle_obstructed', 'placement_collision', 'zone_containment_violation', 'placement_outside_floor'}
                and set(f['subjectRefs']).intersection(REPLACEMENTS) for f in spatial['findings']), 'Replacement geometry warning'
            saved = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, base)
            write_json(out / 'candidate.json', saved['layout'])
            write_json(out / 'operations.json', ops)
            report = dict(status='validated', baseRevision=base, candidateRevision=saved['revision'], checks=checks,
                          layoutHashes=hashes(target.parent), assetFiles=files, placementCount=len(candidate['placements']),
                          rejectedAssets=list(REJECTED_ASSETS),
                          limitations=['Visual vehicle bounds, not operating or traffic envelopes.',
                                       'Roadster and Temerario excluded following native visual review and user request; original files retained.'])
        finally:
            host.close()
    write_json(out / 'report.json', report)
    print(json.dumps({k: report[k] for k in ('status', 'placementCount', 'checks')}), flush=True)


if __name__ == '__main__':
    main()
