"""Stage and explicitly publish appearance-only changes to saved Factory 02."""
from collections import Counter, defaultdict
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations
from tools.add_factory02_parking_office import hashes, write_json, verify_native_candidate

STORE = ROOT / '.runtime/facility-layout'
LAYOUT = 'fl-independent-factory-20260928'
RELATIVE = Path('layouts/local/site-local/layouts') / (LAYOUT + '.json')
BASE = 'ddb1120745f382c756361841f9fe1739c261eb922ec5191464ccfa7fab31637e'
PALETTE = {
    'walls': '#e3e8e8', 'racking': '#356f9e', 'benches': '#4b9080',
    'robots': '#dd8642', 'guards': '#667680', 'machines': '#bac9ce',
    'tooling': '#7b969d', 'cabinets': '#407e8c', 'handling': '#d8ad42',
    'tables': '#e8eceb', 'chairs': '#477984', 'office': '#92a9b4',
    'rubber': '#353d43', 'pallets': '#b3a184', 'utility': '#75958a',
}
GROUPS = {
    'racking': ['asset-pallet-rack', 'asset-tooling-shelves'],
    'benches': ['asset-workbench-w84-d48', 'asset-workbench-w72-d36',
                'asset-workbench-w60-d60', 'asset-mobile-folding-worktable'],
    'robots': ['asset-abb-irb6650-robot'],
    'guards': ['asset-5987t55-wire-mesh-machine-guard-panel'],
    'machines': ['asset-doosan-dbc130-ii', 'asset-cnc-mill', 'asset-haas-st30-lathe',
                 'asset-lathe-acer-1760g', 'asset-vertical-band-saw',
                 'asset-okamoto-surface-grinder', 'asset-sinker-edm',
                 'asset-lathe-hardinge-hlv', 'asset-kalamazoo-h9aw-horizontal-band-saw'],
    'tooling': ['asset-carr-lane-cl-400-ptpb', 'asset-assembled-laboratory-workstation'],
    'cabinets': ['asset-roll-away-cabinet', 'asset-hideaway-cabinet', 'asset-user-library-mobile-cart'],
    'handling': ['asset-lift-table-30x96', 'asset-pallet-truck-simple', 'asset-crane-8-ton',
                 'asset-crane-2-ton', 'asset-crane-montagem', 'asset-mobile-lift-mmle-50d',
                 'asset-all-terrain-pallet-truck', 'asset-2329t24-steel-flush-platform-truck',
                 'asset-centralizing-jack', 'asset-reversible-fork-lift-truck'],
    'tables': ['asset-5589t51-round-plastic-folding-table', 'asset-floor-fan-white',
               'asset-user-library-sink-1'],
    'chairs': ['asset-chair-black'],
    'office': ['asset-import-cubicle'],
    'rubber': ['asset-factory02-perimeter-yard-bumper', 'asset-factory02-parking-wheel-stop'],
    'pallets': ['asset-pallet-1200x1000'],
    'utility': ['asset-green-garbage-container'],
}
PRESERVE = {
    'asset-operator', 'asset-forklift', 'asset-forklift-2610x2264x986-minimum-height-green',
    'asset-desk-1400-clear-wood', 'asset-screen-21', 'asset-keyboard', 'asset-mouse',
    'asset-phone-tel1', 'asset-computer-case', 'asset-kitchen-assembly',
    'asset-import-car-93', 'asset-import-tesla-roadster',
    'asset-truck-40ft-container-straight', 'asset-truck-20ft-container',
}


def operations(before, catalog):
    by_asset = {asset: group for group, assets in GROUPS.items() for asset in assets}
    members = defaultdict(list)
    for p in before['placements']:
        aid = p['assetId']
        if aid in PRESERVE:
            continue
        group = by_asset.get(aid)
        if group is None:
            a = catalog[aid]
            assert a['category'] == 'Building Structures' and 'wall' in a['tags'], aid
            group = 'walls'
        # Office task chairs stay charcoal; lunchroom seating gets the muted teal.
        if aid == 'asset-chair-black' and 'cafeteria' not in p['placementId']:
            group = 'rubber'
        members[group].append(p['placementId'])
    return [dict(op='set_appearance', placementIds=ids, color=PALETTE[group])
            for group, ids in sorted(members.items())], dict(members)


def audit(before, after):
    a, b = deepcopy(before), deepcopy(after)
    a.pop('updatedAt', None); b.pop('updatedAt', None)
    for doc in (a, b):
        for p in doc['placements']:
            p.pop('appearance', None)
    assert a == b, 'A non-appearance field changed'
    original = {p['placementId']: p for p in before['placements']}
    for p in after['placements']:
        if p['assetId'] in PRESERVE:
            assert p == original[p['placementId']], p['placementId']
    return dict(geometryAndNonAppearanceFieldsUnchanged=True,
                placements=len(after['placements']),
                coloredPlacements=sum(p.get('appearance') != original[p['placementId']].get('appearance')
                                      for p in after['placements']),
                movementPrograms=len(after['extensions']['facilityNavigation']['movementPrograms']))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--publish', action='store_true')
    parser.add_argument('--native-report', type=Path)
    args = parser.parse_args()
    out = args.output.resolve(); target = STORE / RELATIVE
    manifest = ROOT / PRIVATE_ASSET_MANIFEST
    if args.publish:
        report = json.loads((out / 'report.json').read_text())
        assert report['status'] == 'validated' and args.native_report
        assert target.read_bytes() == (out / 'before.json').read_bytes(), 'Live layout changed'
        assert hashes(target.parent) == report['layoutHashes'], 'Saved layouts changed'
        assert hashlib.sha256(manifest.read_bytes()).hexdigest() == report['catalogHash']
        candidate = json.loads((out / 'candidate.json').read_text())
        verify_native_candidate(json.loads(args.native_report.read_text()), candidate,
                                (out / 'validation-store' / RELATIVE).read_bytes())
        assert layout_revision(candidate) == report['candidateRevision']
        audit(json.loads((out / 'before.json').read_text()), candidate)
        host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
        try:
            saved = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, BASE)
        finally:
            host.close()
        expected = deepcopy(candidate); expected['updatedAt'] = saved['layout']['updatedAt']
        assert saved['layout'] == expected
        others = lambda values: {k: v for k, v in values.items() if k != target.name}
        assert others(hashes(target.parent)) == others(report['layoutHashes'])
        write_json(out / 'saved.json', saved['layout'])
        report.update(status='saved', savedRevision=saved['revision'],
                      nativeReport=str(args.native_report.resolve()), otherLayoutsUnchanged=True)
    else:
        raw = target.read_bytes(); before = json.loads(raw)
        assert layout_revision(before) == BASE, 'Saved Factory 02 changed'
        out.mkdir(parents=True, exist_ok=False)
        (out / 'before.json').write_bytes(raw)
        copytree(_native_fs_path(STORE / 'authorities'), _native_fs_path(out / 'validation-store/authorities'))
        copytree(_native_fs_path(STORE / 'layouts/local'), _native_fs_path(out / 'validation-store/layouts/local'))
        host = LocalFacilityLayoutHost(out / 'validation-store', private_assets=True, private_asset_root=ROOT)
        try:
            catalog = {a['assetId']: a for a in json.loads(manifest.read_text())['assets']}
            ops, groups = operations(before, catalog)
            candidate = apply_facility_layout_operations(before, ops)['document']
            checks = audit(before, candidate)
            saved = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, BASE)
            audit(before, saved['layout'])
            write_json(out / 'candidate.json', saved['layout'])
            write_json(out / 'operations.json', ops)
            write_json(out / 'validation.json', {k: saved[k] for k in
                       ('dependencies', 'spatialDiagnostics', 'routingDiagnostics')})
            report = dict(status='validated', baseRevision=BASE, candidateRevision=saved['revision'],
                          catalogHash=hashlib.sha256(manifest.read_bytes()).hexdigest(),
                          layoutHashes=hashes(target.parent), palette=PALETTE,
                          groups={k: len(v) for k, v in groups.items()}, **checks)
        finally:
            host.close()
        assert target.read_bytes() == raw
    write_json(out / 'report.json', report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
