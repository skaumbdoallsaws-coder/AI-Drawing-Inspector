"""Add flush gold edging to the five existing Hall of Warriors wall faces."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools'), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from tools.apex_equipment_materials import unpack, pack, material, np
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

OUT = ROOT/'.runtime/private-gym-warrior-trim-20261010'
WIDTH = .025
TARGETS = { 'pl-gym-wellness-'+key: face for key, face in [
    ('work-north-left', 'positive_z'), ('conf-north-left', 'positive_z'),
    ('lounge-north-right', 'positive_z'), ('lounge-north-left', 'positive_z'),
    ('corridor-west', 'positive_x')]
}


def trim_box(raw, face, width=WIDTH, tangent_interval=None):
    """Partition a local box face, preserving other finishes and its solid envelope."""
    assert face in ('positive_x', 'positive_z', 'negative_x', 'negative_z')
    doc, data = unpack(raw)
    primitive = doc['meshes'][0]['primitives'][0]
    assert primitive['attributes'].keys() == {'POSITION'} and primitive.get('mode', 4) == 4
    assert 'material' not in primitive, 'Expected the untextured authored wall core'

    def read(index):
        a = doc['accessors'][index]
        b = doc['bufferViews'][a['bufferView']]
        assert not a.get('sparse') and not b.get('byteStride')
        size = 3 if a['type'] == 'VEC3' else 1
        dtype = {5126: '<f4', 5123: '<u2', 5125: '<u4'}[a['componentType']]
        return np.frombuffer(data, dtype=dtype, count=a['count']*size,
            offset=b.get('byteOffset', 0)+a.get('byteOffset', 0)).reshape((-1, size)).copy()

    points = read(primitive['attributes']['POSITION'])
    faces = read(primitive['indices']).reshape((-1, 3))
    assert points.shape == (8, 3), 'Not an authored box'
    bounds = np.array([points.min(axis=0), points.max(axis=0)])
    assert all(len(np.unique(points[:, a])) == 2 for a in range(3))
    axis, tangent = (0, 2) if face.endswith('_x') else (2, 0)
    sign = 1 if face.startswith('positive_') else -1
    plane = bounds[1 if sign > 0 else 0, axis]
    front = np.all(np.isclose(points[faces, axis], plane, atol=1e-7, rtol=0), axis=1)
    assert np.count_nonzero(front) == 2
    full_u0, full_u1 = bounds[:, tangent]
    u0, u1 = tangent_interval if tangent_interval is not None else (full_u0, full_u1)
    assert full_u0 <= u0 < u1 <= full_u1, 'Trim interval outside wall'
    y0, y1 = bounds[:, 1]
    assert 0 < width < min(u1-u0, y1-y0)/2
    vertices, indices = [], []

    def rectangle(a, b, c, d):
        offset = len(vertices)
        for u, y in [(a, c), (b, c), (b, d), (a, d)]:
            p = [0., float(y), 0.]
            p[tangent], p[axis] = float(u), float(plane)
            vertices.append(p)
        winding = [[0, 1, 2], [0, 2, 3]] if axis == 2 else [[0, 2, 1], [0, 3, 2]]
        if sign < 0:
            winding = [triangle[::-1] for triangle in winding]
        indices.extend([[offset+i for i in triangle] for triangle in winding])

    rectangle(u0+width, u1-width, y0+width, y1-width)
    if full_u0 < u0:
        rectangle(full_u0, u0, y0, y1)
    if u1 < full_u1:
        rectangle(u1, full_u1, y0, y1)
    plain_count = len(indices)
    rectangle(u0, u1, y0, y0+width)
    rectangle(u0, u1, y1-width, y1)
    rectangle(u0, u0+width, y0+width, y1-width)
    rectangle(u1-width, u1, y0+width, y1-width)
    vertices = np.asarray(vertices, dtype='<f4')
    indices = np.asarray(indices, dtype='<u2')
    triangles = vertices[indices]
    cross = np.cross(triangles[:, 1]-triangles[:, 0], triangles[:, 2]-triangles[:, 0])
    assert np.all(cross[:, axis]*sign > 0), 'Inward-facing trim'
    area = np.linalg.norm(cross, axis=1).sum()/2
    assert np.isclose(area, (full_u1-full_u0)*(y1-y0), atol=1e-5, rtol=1e-6), 'Face coverage changed'
    assert np.all(vertices >= bounds[0]) and np.all(vertices <= bounds[1])

    def append(array, kind, component):
        nonlocal data
        array = np.ascontiguousarray(array)
        data += b'\0' * (-len(data) % 4)
        view = len(doc['bufferViews'])
        doc['bufferViews'].append(dict(buffer=0, byteOffset=len(data), byteLength=array.nbytes))
        data += array.tobytes()
        values = array.reshape((-1, 3 if kind == 'VEC3' else 1))
        accessor = len(doc['accessors'])
        doc['accessors'].append(dict(bufferView=view, componentType=component, type=kind,
            count=len(values), min=values.min(axis=0).tolist(), max=values.max(axis=0).tolist()))
        return accessor

    primitive['indices'] = append(faces[~front].astype('<u2'), 'SCALAR', 5123)
    position = append(vertices, 'VEC3', 5126)
    materials = doc.setdefault('materials', [])
    gold = material('gold')
    if gold not in materials:
        materials.append(gold)
    gold_index = materials.index(gold)
    doc['meshes'][0]['primitives'].extend([
        dict(attributes={'POSITION': position}, indices=append(indices[:plain_count], 'SCALAR', 5123), mode=4),
        dict(attributes={'POSITION': position}, indices=append(indices[plain_count:], 'SCALAR', 5123), mode=4, material=gold_index)])
    doc['buffers'][0]['byteLength'] = len(data)
    payload = pack(doc, data)
    return payload, dict(face=face, trimWidthMeters=width, bounds=bounds.tolist(),
        surfaceArea=float(area), goldArea=float(np.linalg.norm(cross[plain_count:], axis=1).sum()/2),
        originalTriangles=len(faces), displayTriangles=len(faces)-2+len(indices), unchangedOtherTriangles=len(faces)-2,
        localTangentInterval=[float(u0), float(u1)],
        solidEnvelopePreserved=True, unchangedOtherFaces=True,
        sourceSha256=hashlib.sha256(raw).hexdigest(), displaySha256=hashlib.sha256(payload).hexdigest())


def audit(before, after, replacements):
    assert set(replacements) == set(TARGETS)
    expected = deepcopy(before)
    for p in expected['placements']:
        if p['placementId'] in replacements:
            assert set(replacements[p['placementId']]) == {'assetId', 'assetDefinitionRevision'}
            p.update(replacements[p['placementId']])
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unrelated geometry, artwork, transforms or appearance changed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'publish', 'save'])
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
            assert all(hashes[k] == v for k, v in report['layoutHashes'].items() if k not in (target.name, 'registry.json'))
            report.update(status='saved', savedRevision=receipt['revision'], otherLayoutsUnchanged=True,
                savedDocumentReloadMatches=True)
        write(OUT/'report.json', report)
        print(report['status'])
        return
    raw, catalog_raw = target.read_bytes(), manifest.read_bytes()
    before, library = json.loads(raw), json.loads(catalog_raw)
    for name, content in [('before.json', raw), ('catalog-before.json', catalog_raw)]:
        file = OUT/name
        if file.exists():
            assert file.read_bytes() == content, 'Staging source changed'
        else:
            file.write_bytes(content)
    by_id = {a['assetId']: a for a in library['assets']}
    original_hashes, variant_hashes, bindings, checks = {}, {}, {}, []
    for pid, face in TARGETS.items():
        p = next(p for p in before['placements'] if p['placementId'] == pid)
        assert p['assetId'] == pid.replace('pl-', 'asset-', 1)
        old = by_id[p['assetId']]
        assert old['sourceToCanonical'] == np.eye(4).flatten().tolist()
        payload, evidence = trim_box((ROOT/old['artifact']).read_bytes(), face)
        relative = 'generated/industrial_assets/private_gym/warrior-trim/'+pid+'-'+evidence['displaySha256'][:16]+'.glb'
        file = staged/relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(payload)
        new = deepcopy(old)
        new.update(assetId=old['assetId']+'-gold-edge', artifact=relative,
            displayName=old['displayName']+' - Gold Edge')
        new['description'] += ' Hallway-facing 25 mm gold edge finish; physical envelope unchanged.'
        new['source'] = dict(kind='authored-primitive', generator='trim_private_gym_warrior_walls.py',
            originalAssetId=old['assetId'], originalSha256=evidence['sourceSha256'])
        new['tags'] += ['APEX', 'gold trim']
        assert new['assetId'] not in by_id
        library['assets'].append(new)
        bindings[pid] = new['assetId']
        original_hashes[old['artifact']] = evidence['sourceSha256']
        variant_hashes[relative] = evidence['displaySha256']
        checks.append(dict(placementId=pid, **evidence))
    library['summary']['total'] = len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST, library)
    stage = OUT/'validation-store'
    for folder in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(stage/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=staged)
    try:
        catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
        replacements = {pid: {k: catalog[aid][k] for k in ['assetId', 'assetDefinitionRevision']} for pid, aid in bindings.items()}
        for pid, aid in bindings.items():
            old_id = next(p['assetId'] for p in before['placements'] if p['placementId'] == pid)
            assert catalog[aid]['definition']['geometry'] == catalog[old_id]['definition']['geometry'], 'Authoritative footprint changed'
        candidate = deepcopy(before)
        for p in candidate['placements']:
            if p['placementId'] in replacements:
                p.update(replacements[p['placementId']])
        audit(before, candidate, replacements)
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
    ids = set(TARGETS) | {'pl-gym-wellness-conf-north-right', 'pl-gym-wellness-work-north-right'}
    fixture['placements'] = [p for p in fixture['placements'] if p['placementId'] in ids]
    finish = fixture['extensions']['facilityPerimeterWalls']['settings']['exteriorFinish']
    finish['fittedArtworks'] = [a for a in finish['fittedArtworks'] if a['artworkId'].startswith('hall-warrior-')]
    finish['wallFaces'] = []
    aids = {p['assetId'] for p in fixture['placements']}
    aids.update(next(p['assetId'] for p in before['placements'] if p['placementId'] == pid) for pid in TARGETS)
    entries = {a['assetId']: a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json', dict(layout=fixture, catalog=[catalog[aid] for aid in sorted(aids)],
        originalPlacements=[p for p in before['placements'] if p['placementId'] in ids],
        ids=[a['artworkId'] for a in finish['fittedArtworks']],
        artifacts={aid: dict(url='/'+a['artifact'], sourceToCanonical=a['sourceToCanonical']) for aid, a in entries.items()}))
    print('validated')


if __name__ == '__main__':
    main()
