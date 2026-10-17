"""Remove the low bookshelf and finish only the private office's interior wall edges."""
from copy import deepcopy
from io import BytesIO
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from tools.apex_equipment_materials import unpack, trimesh, np
from tools.trim_private_gym_warrior_walls import trim_box
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

OUT = ROOT/'.runtime/private-gym-office-trim-20261010'
FLOOR_SHELF = 'pl-39702ef88f4cc7c394f8dccf'
WALL_SHELF = 'pl-804b2c3a923700b7c47633b2'
POOL_WALL = 'pl-gym-pool-connection-south'
TARGETS = {
    'pl-gym-wellness-work-north-left': 'negative_z',
    'pl-gym-wellness-work-north-right': 'negative_z',
    'pl-gym-wellness-meeting-work-divider': 'positive_x',
    'pl-gym-wellness-work-cafe-divider': 'positive_z',
    POOL_WALL: 'negative_x',
}
DEPENDENTS = {WALL_SHELF, 'pl-gym-office-inspectorpro-wall-logo'}


def changed_document(before, replacements):
    assert set(replacements) == set(TARGETS)
    removed = [p for p in before['placements'] if p['placementId'] == FLOOR_SHELF]
    assert len(removed) == 1 and removed[0]['assetId'] == 'asset-gym-office-bookshelf-floor-books'
    result = deepcopy(before)
    result['placements'] = [p for p in result['placements'] if p['placementId'] != FLOOR_SHELF]
    rebound = set()
    for p in result['placements']:
        if p['placementId'] in replacements:
            binding = replacements[p['placementId']]
            assert set(binding) == {'assetId', 'assetDefinitionRevision'}
            p.update(binding)
        snap = p.get('snapRelationship') or {}
        if snap.get('supportPlacementId') in replacements:
            snap['supportAssetDefinitionRevision'] = replacements[snap['supportPlacementId']]['assetDefinitionRevision']
            rebound.add(p['placementId'])
    assert rebound == DEPENDENTS, 'Wall dependency set changed'
    return result


def audit(before, after, replacements):
    expected = changed_document(before, replacements)
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unexpected change outside requested shelf and office-facing finish'


def make_variant(before, library_by_id, pid):
    placements = {p['placementId']:p for p in before['placements']}
    p = placements[pid]
    old = library_by_id[p['assetId']]
    assert p['transform']['quaternion'] == dict(x=0,y=0,z=0,w=1) and p['transform']['scale'] == 1
    assert old['sourceToCanonical'] == np.eye(4).flatten().tolist()
    raw = (ROOT/old['artifact']).read_bytes()
    doc, data = unpack(raw)
    local_face, interval = TARGETS[pid], None
    if pid == POOL_WALL:
        # This mural wall has a 90-degree root rotation: local x maps to world -z.
        assert doc['nodes'][2]['matrix'] == [0,0,-1,0,0,1,0,0,1,0,0,0,0,0,0,1]
        south = placements['pl-gym-wellness-work-cafe-divider']
        north = placements['pl-gym-wellness-work-north-right']
        z_min = south['transform']['position']['z'] + library_by_id[south['assetId']]['dimensions']['depth']/2
        z_max = north['transform']['position']['z'] - library_by_id[north['assetId']]['dimensions']['depth']/2
        origin = p['transform']['position']['z']
        interval = (origin-z_max, origin-z_min)
        local_face = 'negative_z'
    payload, evidence = trim_box(raw, local_face, tangent_interval=interval)
    new_doc, new_data = unpack(payload)
    assert new_data.startswith(data)
    assert new_doc['nodes'] == doc['nodes'] and new_doc['scenes'] == doc['scenes']
    assert new_doc['meshes'][1:] == doc['meshes'][1:]
    count = len(doc['meshes'][0]['primitives'])
    assert new_doc['meshes'][0]['primitives'][1:count] == doc['meshes'][0]['primitives'][1:]
    for key in ['images', 'textures', 'samplers']:
        assert new_doc.get(key) == doc.get(key)
    for i, value in enumerate(doc.get('materials', [])):
        assert new_doc['materials'][i] == value
    original = trimesh.load(BytesIO(raw), file_type='glb', force='scene', process=False)
    finished = trimesh.load(BytesIO(payload), file_type='glb', force='scene', process=False)
    assert np.array_equal(original.bounds, finished.bounds)
    assert np.isclose(sum(m.area for m in original.geometry.values()),
        sum(m.area for m in finished.geometry.values()), rtol=1e-6, atol=1e-5)
    evidence.update(placementId=pid, canonicalFace=TARGETS[pid], existingArtworkAndFinishesPreserved=True)
    return old, payload, evidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage','publish','save'])
    phase = parser.parse_args().phase
    OUT.mkdir(parents=True, exist_ok=True)
    staged = OUT/'staged-project'
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    if phase != 'stage':
        report = json.loads((OUT/'report.json').read_bytes())
        assert target.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed'
        for relative, digest in report['originalAssetHashes'].items():
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == digest
        if phase == 'publish':
            assert report['status'] == 'validated'
            assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes(), 'Library changed'
            proof = json.loads((OUT/'browser-check.json').read_bytes())
            assert proof['status'] == 'passed'
            assert proof['candidateHash'] == hashlib.sha256((OUT/'candidate.json').read_bytes()).hexdigest()
            for relative, digest in report['variantHashes'].items():
                raw = (staged/relative).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == digest
                if (ROOT/relative).exists():
                    assert (ROOT/relative).read_bytes() == raw
                else:
                    RevisionedAuthorityRepository._atomic_write(ROOT/relative, raw)
            RevisionedAuthorityRepository._atomic_write(manifest, (staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status'] = 'published'
        else:
            assert report['status'] == 'published'
            assert manifest.read_bytes() == (staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for relative, digest in report['variantHashes'].items():
                assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == digest
            before = json.loads((OUT/'before.json').read_bytes())
            candidate = json.loads((OUT/'candidate.json').read_bytes())
            audit(before, candidate, report['replacements'])
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try:
                receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, report['baseRevision'])
                audit(before, receipt['layout'], report['replacements'])
                assert json.loads(target.read_bytes()) == receipt['layout']
            finally:
                host.close()
            write(OUT/'saved.json', receipt['layout'])
            hashes = saved_hashes()
            assert all(hashes[k] == v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report.update(status='saved', savedRevision=receipt['revision'], otherLayoutsUnchanged=True)
        write(OUT/'report.json', report)
        print(report['status'])
        return
    raw, catalog_raw = target.read_bytes(), manifest.read_bytes()
    before, library = json.loads(raw), json.loads(catalog_raw)
    for name, content in [('before.json',raw),('catalog-before.json',catalog_raw)]:
        file = OUT/name
        if file.exists():
            assert file.read_bytes() == content, 'Staging source changed'
        else:
            file.write_bytes(content)
    by_id = {a['assetId']:a for a in library['assets']}
    original_hashes, variant_hashes, bindings, checks = {}, {}, {}, []
    for pid in TARGETS:
        old, payload, evidence = make_variant(before, by_id, pid)
        relative = 'generated/industrial_assets/private_gym/office-trim/'+pid+'-'+evidence['displaySha256'][:16]+'.glb'
        file = staged/relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(payload)
        new = deepcopy(old)
        new.update(assetId=old['assetId']+'-office-edge', artifact=relative,
            displayName=old['displayName']+' - Office Gold Edge')
        new['description'] += ' Office-facing 25 mm gold edge finish; physical envelope and reverse-side artwork unchanged.'
        new['source'] = dict(kind='authored-primitive', generator=Path(__file__).name,
            originalAssetId=old['assetId'], originalSha256=evidence['sourceSha256'])
        new['tags'] += ['office gold trim']
        assert new['assetId'] not in by_id
        library['assets'].append(new)
        bindings[pid] = new['assetId']
        original_hashes[old['artifact']] = evidence['sourceSha256']
        variant_hashes[relative] = evidence['displaySha256']
        checks.append(evidence)
    library['summary']['total'] = len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST, library)
    stage = OUT/'validation-store'
    for folder in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(stage/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=staged)
    try:
        catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
        replacements = {pid:{k:catalog[aid][k] for k in ['assetId','assetDefinitionRevision']} for pid,aid in bindings.items()}
        for pid, aid in bindings.items():
            old_id = next(p['assetId'] for p in before['placements'] if p['placementId'] == pid)
            assert catalog[aid]['definition']['geometry'] == catalog[old_id]['definition']['geometry']
        candidate = changed_document(before, replacements)
        spatial = host.service._diagnose_spatial(host.principal(), 'site-local', candidate)
        write(OUT/'spatial.json', spatial)
        host.service._require_spatially_valid(spatial)
        receipt = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, layout_revision(before))
        candidate = receipt['layout']
        audit(before, candidate, replacements)
    finally:
        host.close()
    write(OUT/'candidate.json', candidate)
    write(OUT/'report.json', dict(status='validated', baseRevision=layout_revision(before), replacements=replacements,
        checks=checks, layoutHashes=saved_hashes(), originalAssetHashes=original_hashes, variantHashes=variant_hashes))
    fixture = deepcopy(candidate)
    ids = set(TARGETS) | DEPENDENTS
    ids.update(p['placementId'] for p in candidate['placements']
        if p.get('metadata',{}).get('room') == 'work' or p['placementId'].startswith('pl-gym-office-'))
    fixture['placements'] = [p for p in fixture['placements'] if p['placementId'] in ids]
    finish = fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks'] = [a for a in finish['fittedArtworks'] if a['artworkId'] == 'hall-warrior-viking']
    finish['wallFaces'] = []
    aids = {p['assetId'] for p in fixture['placements']}
    aids.update(next(p['assetId'] for p in before['placements'] if p['placementId']==pid) for pid in TARGETS)
    entries = {a['assetId']:a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json', dict(layout=fixture, catalog=[catalog[aid] for aid in sorted(aids)],
        originalPlacements=[p for p in before['placements'] if p['placementId'] in ids],
        ids=[a['artworkId'] for a in finish['fittedArtworks']],
        artifacts={aid:dict(url='/'+a['artifact'], sourceToCanonical=a['sourceToCanonical']) for aid,a in entries.items()}))
    print('validated')


if __name__ == '__main__':
    main()
