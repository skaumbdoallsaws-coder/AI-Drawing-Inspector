"""Open the lunchroom kitchen while retaining its cabinet back wall."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
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
from ai_inspector.facility_layout.perimeter_walls import KEY
from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb
from tools.add_factory02_dispatch_office import LAYOUT_ID, SITE, STORE
from tools.add_factory02_kitchen_walls import wall_shape
from tools.add_factory02_parking_office import hashes, write_json, verify_native_candidate
from tools.audit_independent_factory_layer2 import footprint

BASE = '56dd4bbb1ceab481659a35ddc8c1e2ec9f3ee99765d14a1a1a63e6717fc9f1d0'
ASSET = 'asset-factory02-perimeter-lunch-kitchen-back'
PLACEMENT = 'pl-lunchroom-wall-kitchen-back'
BOUNDS = (331.925, 51.925, 332.075, 58.675)
SPEC = dict(assetId=ASSET, displayName='Lunchroom kitchen back wall', category='Building Structures',
    dimensions=dict(width=.15, depth=6.75, height=2.8),
    artifact='generated/industrial_assets/factory02_lunchroom/kitchen-back/model.glb',
    description='Retained concept kitchen back wall; no structural or fire qualification.',
    tags=['wall','perimeter','lunchroom'], source=dict(kind='authored-primitive',generator=Path(__file__).name),
    sourceToCanonical=[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1])


def operations(before, catalog):
    if before['layoutId'] != LAYOUT_ID or layout_revision(before) != BASE:
        raise ValueError('Factory 02 changed; review the current saved layout.')
    settings = before.get('extensions', {}).get(KEY, {}).get('settings', {})
    if settings.get('boundary') != [dict(x=324.8,z=52),dict(x=332,z=52),
                                    dict(x=332,z=58.6),dict(x=324.8,z=58.6)]:
        raise ValueError('Expected kitchen enclosure is missing.')
    asset = catalog[ASSET]
    return [dict(op='set_perimeter_walls', wallSettings=None),
        dict(op='place_asset', placement=dict(placementId=PLACEMENT,assetId=ASSET,
            assetDefinitionRevision=asset['assetDefinitionRevision'],
            transform=dict(position=dict(x=332,y=0,z=55.3),quaternion=dict(x=0,y=0,z=0,w=1),scale=1),
            positionMode='locked',snapRelationship=None,
            metadata=dict(instanceLabel='Kitchen cabinet back wall',inputMethod='independent-authoring')))]


def audit(before, after, catalog):
    restored = deepcopy(after)
    back = next(p for p in restored['placements'] if p['placementId'] == PLACEMENT)
    restored['placements'].remove(back)
    assert KEY not in after['extensions']
    restored['extensions'][KEY] = deepcopy(before['extensions'][KEY])
    restored['updatedAt'] = before['updatedAt']
    assert restored == before, 'Unrelated layout content changed'
    retained = footprint(back, catalog[ASSET])
    assert retained.symmetric_difference(box(*BOUNDS)).area < 1e-8
    assert retained.symmetric_difference(wall_shape(before).intersection(box(*BOUNDS))).area < 1e-8
    assert not retained.intersects(box(324.7,51.9,331.9,58.7))
    return dict(kitchenFrontAndSidesRemoved=True,cabinetBackWallRetained=True,
                unchangedExistingPlacements=len(before['placements']),allOtherContentUnchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--publish-assets',action='store_true')
    parser.add_argument('--publish',action='store_true')
    parser.add_argument('--native-report',type=Path)
    args = parser.parse_args()
    out = args.output.resolve()
    directory = STORE/'layouts/local/site-local/layouts'
    target = directory/(LAYOUT_ID+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    staged = out/'staged-project'
    if args.publish_assets or args.publish:
        report = json.loads((out/'report.json').read_text())
        assert target.read_bytes() == (out/'before.json').read_bytes(), 'Saved layout changed'
        assert hashes(directory) == report['layoutHashes'], 'Saved layouts changed'
        payload = (staged/PRIVATE_ASSET_MANIFEST).read_bytes()
        if args.publish_assets:
            assert report['status'] == 'validated'
            assert manifest.read_bytes() == (out/'catalog-before.json').read_bytes()
            dest = ROOT/SPEC['artifact']
            assert not dest.exists()
            dest.parent.mkdir(parents=True,exist_ok=True)
            RevisionedAuthorityRepository._atomic_write(dest,(staged/SPEC['artifact']).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,payload)
            report['status'] = 'assets-published'
        else:
            assert report['status'] == 'assets-published' and args.native_report
            assert manifest.read_bytes() == payload
            candidate = json.loads((out/'candidate.json').read_text())
            assert layout_revision(candidate) == report['candidateRevision']
            verify_native_candidate(json.loads(args.native_report.read_text()),candidate,
                (out/'validation-store/layouts/local/site-local/layouts'/target.name).read_bytes())
            host = LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:
                saved = host.service.save_layout(host.principal(),SITE,LAYOUT_ID,candidate,BASE)
            finally:
                host.close()
            normalized = deepcopy(saved['layout']);normalized['updatedAt'] = candidate['updatedAt']
            assert normalized == candidate
            assert {k:v for k,v in hashes(directory).items() if k!=target.name} == {
                k:v for k,v in report['layoutHashes'].items() if k!=target.name}
            write_json(out/'saved.json',saved['layout'])
            report.update(status='saved',savedRevision=saved['revision'],nativeEvidencePath=str(args.native_report.resolve()))
        write_json(out/'report.json',report)
        print(json.dumps(dict(status=report['status'])))
        return

    before_bytes = target.read_bytes();before = json.loads(before_bytes)
    assert layout_revision(before) == BASE
    out.mkdir(parents=True,exist_ok=False)
    (out/'before.json').write_bytes(before_bytes)
    (out/'catalog-before.json').write_bytes(manifest.read_bytes())
    library = json.loads(manifest.read_text())
    assert all(a['assetId'] != ASSET for a in library['assets'])
    library['assets'].append(SPEC);library['summary']['total'] = len(library['assets'])
    write_json(staged/PRIVATE_ASSET_MANIFEST,library)
    artifact = staged/SPEC['artifact'];artifact.parent.mkdir(parents=True,exist_ok=True)
    artifact.write_bytes(build_aabb_proxy_glb(dict(minimum=dict(x=-.075,y=0,z=-3.375),
        maximum=dict(x=.075,y=2.8,z=3.375))))
    stage = out/'validation-store'
    copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'))
    copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'))
    host = LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        ops = operations(before,catalog)
        after = apply_facility_layout_operations(before,ops,updated_at=datetime.now(timezone.utc).isoformat())['document']
        checks = audit(before,after,catalog)
        principal = host.principal()
        dependencies = host.service.validate_dependencies(principal,SITE,after).to_dict()
        spatial = host.service._diagnose_spatial(principal,SITE,after)
        routing = host.service._diagnose_routing(principal,SITE,after)
        write_json(out/'validation.json',dict(dependencies=dependencies,spatial=spatial,routing=routing))
        host.service._require_spatially_valid(spatial);host.service._require_routing_valid(routing)
        saved = host.service.save_layout(principal,SITE,LAYOUT_ID,after,BASE)
        write_json(out/'candidate.json',saved['layout']);write_json(out/'operations.json',ops)
        report = dict(status='validated',baseRevision=BASE,candidateRevision=saved['revision'],
            **checks,totalPlacements=len(after['placements']),layoutHashes=hashes(directory),spatialMetrics=spatial['metrics'])
        write_json(out/'report.json',report)
        print(json.dumps(report))
    finally:
        host.close()


if __name__ == '__main__':
    main()
