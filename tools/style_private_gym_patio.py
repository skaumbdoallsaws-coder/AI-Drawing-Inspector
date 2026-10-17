"""Create scoped APEX finish variants for the saved gym's patio assemblies."""
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
from tools.apex_equipment_materials import annotate, build_variant, source_path, unpack, np, trimesh
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

OUT = ROOT/'.runtime/private-gym-patio-theme-20261009'
TARGETS = {
    'pl-gym-patio-pergola-supports': 'supports',
    'pl-gym-patio-pergola-roof': 'roof',
    'pl-gym-patio-shaded-drinks-table': 'drinks',
    'pl-gym-patio-picnic-table-and-four-chairs': 'picnic',
    'pl-gym-patio-barbecue-grill': 'grill',
}


def component_role(key, faces, bounds):
    lo, hi = np.asarray(bounds)
    if key == 'supports' and faces == 268 and lo[1] > 1.4:
        return 'gold'
    if key == 'roof' and faces == 220 and lo[1] > .469:
        return 'gold'
    if key == 'picnic':
        if faces == 222 and lo[1] > .50:
            return 'gold'
        if .711 < lo[1] < .713 and .731 < hi[1] < .733 and max(abs(lo[0]), abs(hi[0]), abs(lo[2]), abs(hi[2])) < .51:
            return 'gold'
    if key == 'drinks' and faces in (14684, 27468, 2512):
        return 'gold'
    return None


def roles(asset, key):
    raw = source_path(asset).read_bytes()
    doc, _ = unpack(raw)
    result = {str(i): 'frame' for i in range(len(doc['meshes']))}
    if key == 'grill':
        for i, mesh in enumerate(doc['meshes']):
            name = mesh.get('name', '')
            if name.startswith('Parrilla 110x60cm'):
                result[str(i)] = 'steel'
            elif name in ('TAPA GRILL', 'BASE PARRILLA'):
                assert len(mesh['primitives']) == 2
                result[str(i)+':0'] = 'gold'
        assert list(result.values()).count('steel') == 2
        assert list(result.values()).count('gold') == 2
        result['regions'] = [dict(sourceRole='frame', role='gold',
                                  bounds=[[.295, 1.0, -.405], [.36, 1.15, .405]])]
        return result
    annotated, _ = annotate(raw, result)
    scene = trimesh.load(BytesIO(annotated), file_type='glb', force='scene', process=False)
    components = []
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        mesh = scene.geometry[name].copy()
        mesh.apply_transform(transform)
        points = trimesh.transform_points(mesh.vertices, np.asarray(asset['sourceToCanonical']).reshape((4, 4), order='F'))
        welded = mesh.copy()
        welded.merge_vertices()
        assert np.allclose(welded.triangles, mesh.triangles, atol=2e-6, rtol=0)
        for faces in trimesh.graph.connected_components(welded.face_adjacency, nodes=np.arange(len(mesh.faces)), min_len=1):
            vertices = points[mesh.faces[faces]].reshape(-1, 3)
            bounds = np.array([vertices.min(axis=0), vertices.max(axis=0)])
            role = component_role(key, len(faces), bounds)
            if role:
                components.append(dict(mesh=name, faces=len(faces), bounds=bounds.tolist(), role=role))
    expected = dict(supports=8, roof=16, picnic=139, drinks=5)
    assert len(components) == expected[key], (key, len(components))
    result['connectedComponents'] = components
    return result


def audit(before, after, replacements):
    assert set(replacements) == set(TARGETS)
    expected = deepcopy(before)
    for p in expected['placements']:
        if p['placementId'] in replacements:
            assert set(replacements[p['placementId']]) == {'assetId', 'assetDefinitionRevision'}
            p.update(replacements[p['placementId']])
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unrelated content, transforms, or attachments changed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['stage', 'publish', 'save'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    staged = OUT/'staged-project'
    target = STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest = ROOT/PRIVATE_ASSET_MANIFEST
    if args.phase != 'stage':
        report = json.loads((OUT/'report.json').read_bytes())
        assert target.read_bytes() == (OUT/'before.json').read_bytes(), 'Saved gym changed'
        for relative, digest in report['originalAssetHashes'].items():
            assert hashlib.sha256((ROOT/relative).read_bytes()).hexdigest() == digest
        if args.phase == 'publish':
            assert report['status'] == 'validated'
            assert manifest.read_bytes() == (OUT/'catalog-before.json').read_bytes(), 'Library changed'
            proof = json.loads((OUT/'browser-check.json').read_bytes())
            assert proof['status'] == 'passed'
            assert proof['candidateHash'] == hashlib.sha256((OUT/'candidate.json').read_bytes()).hexdigest()
            for relative, digest in report['variantHashes'].items():
                raw = (staged/relative).read_bytes()
                assert hashlib.sha256(raw).hexdigest() == digest
                assert not (ROOT/relative).exists(), 'Variant path already used'
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
    for name, data in [('before.json', raw), ('catalog-before.json', catalog_raw)]:
        dest = OUT/name
        if dest.exists():
            assert dest.read_bytes() == data, 'Staging source changed'
        else:
            dest.write_bytes(data)
    by_id = {a['assetId']: a for a in library['assets']}
    original_hashes, variant_hashes, bindings, checks = {}, {}, {}, []
    for pid, key in TARGETS.items():
        placement = next(p for p in before['placements'] if p['placementId'] == pid)
        assert placement['assetId'] == 'asset-gym-patio-'+key
        old = by_id[placement['assetId']]
        payload, evidence = build_variant(old, roles(old, key))
        relative = 'generated/industrial_assets/private_gym/apex-patio/'+key+'/model.glb'
        dest = staged/relative
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        new = deepcopy(old)
        new.update(assetId=old['assetId']+'-apex-patio', displayName=old['displayName']+' - APEX', artifact=relative)
        new['description'] = old.get('description', '')+' APEX component finishes; original CAD preserved.'
        new['visualImport'] = {k: v for k, v in evidence.items() if k != 'components'}
        new['measuredGeometry'].update(sourceSha256=evidence['displaySha256'], triangles=evidence['triangleCount'])
        new['tags'] = old['tags']+['APEX', 'component materials']
        assert new['assetId'] not in by_id
        library['assets'].append(new)
        bindings[pid] = new['assetId']
        variant_hashes[relative] = evidence['displaySha256']
        original_hashes[old['artifact']] = evidence['previousDisplaySha256']
        original_hashes[evidence['source']] = evidence['sourceSha256']
        write(OUT/'components'/(key+'.json'), evidence)
        checks.append(dict(key=key, triangles=evidence['triangleCount'], groups=evidence['drawGroups'],
                           geometryPreserved=evidence['geometryPreserved'], roles=evidence['roles']))
        print(json.dumps(checks[-1]), flush=True)
    library['summary']['total'] = len(library['assets'])
    write(staged/PRIVATE_ASSET_MANIFEST, library)
    stage = OUT/'validation-store'
    for folder in ['authorities', 'layouts/local']:
        copytree(_native_fs_path(STORE/folder), _native_fs_path(stage/folder), dirs_exist_ok=True)
    host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=staged)
    try:
        catalog = {a['assetId']: a for a in host.authoritative_asset_catalog()}
        replacements = {pid: {k: catalog[aid][k] for k in ['assetId', 'assetDefinitionRevision']} for pid, aid in bindings.items()}
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
    fixture['placements'] = [p for p in fixture['placements'] if p['placementId'].startswith('pl-gym-patio-')]
    fixture['extensions'].pop('facilityPerimeterWalls', None)
    aids = {p['assetId'] for p in fixture['placements']}
    entries = {a['assetId']: a for a in library['assets'] if a['assetId'] in aids}
    write(OUT/'render-fixture.json', dict(layout=fixture, catalog=[catalog[aid] for aid in sorted(aids)],
        artifacts={aid: dict(url='/'+a['artifact'], sourceToCanonical=a['sourceToCanonical']) for aid, a in entries.items()}))
    print('validated')


if __name__ == '__main__':
    main()
