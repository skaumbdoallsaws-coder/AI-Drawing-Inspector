"""Darken only the two mural-facing outdoor wall surfaces."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from tools import add_private_gym_outdoor_art as art
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from ai_inspector.facility_layout.authority_repository import _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.facility_layout.operations import apply_facility_layout_operations

OUT = ROOT/'.runtime/private-gym-outdoor-charcoal-20261009'
COLOR = '#202428'
TARGETS = tuple(s['placement'] for s in art.SPECS)


def painted_settings(before):
    settings = deepcopy(before['extensions']['facilityPerimeterWalls']['settings'])
    faces = settings['exteriorFinish']['wallFaces']
    placements = {p['placementId']: p for p in before['placements']}
    for pid in TARGETS:
        rows = [f for f in faces if f['placementId'] == pid and f['face'] == 'positive_z']
        assert len(rows) <= 1
        if rows:
            assert rows[0]['assetDefinitionRevision'] == placements[pid]['assetDefinitionRevision']
            rows[0]['color'] = COLOR
        else:
            faces.append(dict(placementId=pid, assetDefinitionRevision=placements[pid]['assetDefinitionRevision'],
                              face='positive_z', color=COLOR))
    return settings


def audit(before, after):
    expected = deepcopy(before)
    expected['extensions']['facilityPerimeterWalls']['settings'] = painted_settings(before)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Content beyond the two outward wall finishes changed'
    return dict(outdoorFaces=2, color=COLOR, placementsPreserved=len(before['placements']),
                interiorColorsUnchanged=True, artworkUnchanged=True, geometryUnchanged=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'verify', 'save'])
    phase = parser.parse_args().phase
    OUT.mkdir(parents=True, exist_ok=True)
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    if phase == 'verify':
        from tools import verify_private_gym_outdoor_art as verifier
        verifier.OUT = OUT
        verifier.verify()
        return
    if phase == 'save':
        report = json.loads((OUT/'report.json').read_bytes())
        assert report['status'] == 'validated'
        assert target.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed during review'
        assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes(), 'Library changed during review'
        raw = (OUT/'candidate.json').read_bytes()
        proof = json.loads((OUT/'browser-check.json').read_bytes())
        assert proof['status'] == 'passed' and proof['candidateHash'] == hashlib.sha256(raw).hexdigest()
        before, candidate = json.loads((OUT/'before.json').read_bytes()), json.loads(raw)
        audit(before, candidate)
        host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
        try:
            art.check_targets(candidate, {a['assetId']: a for a in host.authoritative_asset_catalog()})
            receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
            audit(before, receipt['layout'])
            assert json.loads(target.read_bytes()) == receipt['layout']
        finally:
            host.close()
        write(OUT/'saved.json', receipt['layout'])
        hashes = saved_hashes()
        assert all(hashes[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name, 'registry.json'))
        report.update(status='saved', savedRevision=receipt['revision'], savedDocumentReloadMatches=True,
                      otherLayoutsUnchanged=True)
        write(OUT/'report.json', report)
        print(json.dumps(report['checks']))
        return
    raw = target.read_bytes()
    before = json.loads(raw)
    for name, data in [('before.json', raw), ('catalog-before.json', manifest.read_bytes())]:
        dest = OUT/name
        if dest.exists():
            assert dest.read_bytes() == data, 'Staging source changed'
        else:
            dest.write_bytes(data)
    candidate = apply_facility_layout_operations(before,
        [dict(op='set_perimeter_walls', wallSettings=painted_settings(before))])['document']
    checks = audit(before, candidate)
    stage = OUT/'validation-store'
    for folder in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(stage/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=ROOT)
    try:
        catalog = host.authoritative_asset_catalog()
        art.check_targets(before, {a['assetId']: a for a in catalog})
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT/'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
        audit(before, receipt['layout'])
    finally:
        host.close()
    write(OUT/'candidate.json', receipt['layout'])
    fixture = json.loads((art.OUT/'render-fixture.json').read_bytes())
    fixture['layout'] = deepcopy(receipt['layout'])
    fixture['layout']['placements'] = [p for p in candidate['placements'] if p['placementId'] in TARGETS]
    finish = fixture['layout']['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks'] = [a for a in finish['fittedArtworks'] if a['artworkId'] in fixture['ids']]
    finish['artworks'] = []
    finish['wallFaces'] = [f for f in finish['wallFaces'] if f['placementId'] in TARGETS]
    write(OUT/'render-fixture.json', fixture)
    write(OUT/'report.json', dict(status='validated', baseRevision=layout_revision(before),
                                layoutHashes=saved_hashes(), checks=checks))
    print(json.dumps(checks))


if __name__ == '__main__':
    main()
