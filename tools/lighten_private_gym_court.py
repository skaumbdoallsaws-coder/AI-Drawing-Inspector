"""Change only the three basketball wall appearances, retaining exterior finishes."""
from copy import deepcopy
from datetime import datetime, timezone
import argparse
import hashlib
import json
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

OUT = ROOT / '.runtime/private-gym-light-court-20261007'
IDS = ['pl-private-gym-sports-court-' + face for face in ('back', 'left', 'right')]


def audit(before, after, color):
    expected = deepcopy(before)
    targets = [p for p in expected['placements'] if p['placementId'] in IDS]
    assert len(targets) == 3
    for placement in targets:
        placement['appearance'] = {'color': color}
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unexpected change outside the three wall appearances'
    return dict(recoloredWalls=3, color=color, placementCount=len(after['placements']),
                exteriorUnchanged=True, geometryUnchanged=True, muralsUnchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'save'])
    args = parser.parse_args()
    target = STORE / 'layouts/local/site-local/layouts' / (LAYOUT + '.json')
    if args.phase == 'save':
        report = json.loads((OUT / 'report.json').read_text())
        if report['status'] == 'saved':
            assert json.loads(target.read_bytes()) == json.loads((OUT / 'saved.json').read_bytes())
            print(json.dumps(dict(status='already-saved')))
            return
        assert target.read_bytes() == (OUT / 'before.json').read_bytes(), 'Saved base changed during review'
        raw = (OUT / 'candidate.json').read_bytes()
        native = json.loads((OUT / 'native-check.json').read_text())
        assert native['status'] == 'preview-verified'
        assert native['candidateHash'] == hashlib.sha256(raw).hexdigest()
        before = json.loads((OUT / 'before.json').read_bytes())
        candidate = json.loads(raw)
        audit(before, candidate, report['checks']['color'])
        host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
        try:
            receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
        finally:
            host.close()
        audit(before, receipt['layout'], report['checks']['color'])
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
    reference = next(p for p in before['placements'] if p['placementId'] == 'pl-private-gym-sports-boxing-south')
    color = reference['appearance']['color']
    ops = [dict(op='set_appearance', placementIds=IDS, color=color)]
    candidate = apply_facility_layout_operations(before, ops, updated_at=datetime.now(timezone.utc).isoformat())['document']
    checks = audit(before, candidate, color)
    staged = OUT / 'validation-store'
    for rel in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE / rel), _native_fs_path(staged / rel), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(staged, private_assets=True, private_asset_root=ROOT)
    try:
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT / 'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
    finally:
        host.close()
    audit(before, receipt['layout'], color)
    write(OUT / 'candidate.json', receipt['layout'])
    write(OUT / 'operations.json', ops)
    write(OUT / 'report.json', dict(status='validated', baseRevision=layout_revision(before), checks=checks, layoutHashes=saved_hashes()))
    profile = json.loads((ROOT / '.runtime/private-gym-exterior-20261007/profile.json').read_text())
    profile.update(profileId='private-gym-light-court', origin='http://127.0.0.1:8545', dataRoot=str(OUT), backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()))
    write(OUT / 'profile.json', profile)
    def shot(name, position, target):
        return dict(name=name, position=dict(zip(('x', 'y', 'z'), position)), target=dict(zip(('x', 'y', 'z'), target)), thresholds=dict(detail=1000))
    court = shot('01-light-court', (71.5, 5, 17.8), (71.5, 2.5, 34))
    write(OUT / 'review-config.json', dict(profileId=profile['profileId'],
        requiredAssets=['asset-private-gym-sports-court-' + face for face in ('back', 'left', 'right')],
        requiredWallArt=['apex-emblem', 'discipline', 'higher-everyday'],
        shots=[court, shot('02-exterior-retained', (88, 8, 44), (71, 2, 27))],
        finalShot=dict(court, name='03-saved-light-court')))
    print(json.dumps(dict(status='validated', checks=checks)))


if __name__ == '__main__':
    main()
