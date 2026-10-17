"""Publish reviewed gym-mat models with the existing isolated catalog API checks."""
import math

import import_gym_mat_assets as batch
from import_additional_gym_assets import sha, layout_hashes

ROOT, OUT = batch.ROOT, batch.OUT
read = batch.read
publication = batch.load_helper('gym_catalog_publication', batch.PREVIOUS / 'publish.py')


def check_unchanged(before):
    assert batch.source_hashes() == before['sources'], 'Original CAD files changed'
    assert layout_hashes() == before['layouts'], 'Saved layouts changed'
    for item in read(OUT / 'inventory.json'):
        if item['format'] == '.sldasm':
            prefix = item['sourceRelativePath'].rsplit('/', 1)[0] + '/'
            for name, digest in before['sources'].items():
                if name.startswith(prefix) and not name.rsplit('/', 1)[1].startswith('~$'):
                    assert sha(ROOT / item['target'] / name.rsplit('/', 1)[1]) == digest


def reviewed_entries(items, decisions):
    entries, held, records = [], [], []
    for item in items:
        aid = item['assetId']
        decision = decisions.get(aid, {})
        if decision.get('publish') is False:
            held.append(dict(assetId=aid, source=item['source'], reason=decision['note']))
            continue
        assert decision.get('visuallyReviewed') is True, 'Missing visual review: ' + aid
        target = ROOT / item['target']
        conversion = read(OUT / (aid + '-conversion.json'))
        assert conversion['status'] == 'converted' and not conversion['units'].get('requiresConfirmation'), aid
        assert conversion['sourceSha256'] == item['sourceSha256'] == sha(target / item['source']), aid
        if item['format'] == '.sldasm':
            native = read(target / 'native-export.json')
            assert not native['missing'] and not native['suppressed'] and native['errors'] == 0
            assert len(native['partInstances']) == conversion['verifiedPartInstances'] > 0
            assert native == conversion['nativeEvidence']
        else:
            assert conversion['sourceFaces'] == conversion['meshedFaces'] + len(conversion.get('negligibleFaces', [])), aid
            assert all(f['areaSquareMillimeters'] <= .000001 for f in conversion.get('negligibleFaces', []))
        entry = read(target / 'catalog-entry.json')
        assert entry['displayName'] == decision.get('name', item['displayName']), aid
        assert list(entry['canonicalOrientation']['rotationDegrees'].values()) == decision.get('rotation', [0, 0, 0]), aid
        assert all(math.isfinite(v) and .005 < v < 10 for v in entry['dimensions'].values()), aid
        glb = ROOT / entry['artifact']
        publication.validate_glb_container(glb, maximum_input_bytes=1024*1024*1024)
        evidence = read(target / 'thumbnail-evidence.json')
        assert evidence['passed'] and all(evidence['checks'].values()), aid
        assert evidence['checks'].get('inputTransferFinished') is True, aid
        assert evidence['renderer']['threeRevision'] == '184', aid
        assert sha(glb) == evidence['source']['sha256'] == entry['measuredGeometry']['sourceSha256'], aid
        assert sha(target / 'thumbnail.webp') == evidence['output']['sha256'], aid
        assert evidence['geometry']['triangleCount'] == entry['measuredGeometry']['triangles'], aid
        packed = read(target / 'display-mesh-evidence.json')
        assert packed['sourceTriangles'] == packed['displayTriangles'] == entry['measuredGeometry']['triangles'], aid
        assert packed['maxBoundsChangeMeters'] <= .00001, aid
        assert packed['displaySha256'] == sha(glb) and packed['sourceSha256'] == sha(ROOT / conversion['artifact']), aid
        if 'originalArtifact' in conversion:
            assert sha(ROOT / conversion['originalArtifact']) == conversion['originalArtifactSha256']
            assert conversion['emptyCompoundRepair']['binaryGeometryUnchanged']
        if item['format'] == '.sldasm':
            entry['source']['kind'] = 'assembly'
        entries.append(entry)
        records.append(dict(assetId=aid, name=entry['displayName'], source=item['source'],
            dimensions=entry['dimensions'], bytes=glb.stat().st_size, geometry=evidence['geometry'],
            thumbnailChecks=evidence['checks'], originalCadSha256=item['sourceSha256']))
    return entries, held, records


if __name__ == '__main__':
    publication.check_unchanged = check_unchanged
    publication.reviewed_entries = reviewed_entries
    publication.main()
    result = read(OUT / 'publication-result.json')
    baseline = read(OUT / 'catalog-before.json')['assets']
    original_ids = {entry['assetId'] for entry in baseline}
    result['batchCatalogBefore'] = len(baseline)
    result['newAssetsRelativeToBatchBaseline'] = sum(a['assetId'] not in original_ids for a in result['assets'])
    batch.common.write(OUT / 'publication-result.json', result)
