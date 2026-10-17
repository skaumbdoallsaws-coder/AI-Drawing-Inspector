"""Add the existing InspectorPro artwork to two walls, with revision-bound publication."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from PIL import Image
from ai_inspector.facility_layout.authority_repository import _native_fs_path, RevisionedAuthorityRepository
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb, inspect_glb
from tools.add_factory02_parking_office import hashes, write_json, verify_native_candidate

STORE = ROOT / '.runtime/facility-layout'
LAYOUT = 'fl-independent-factory-20260928'
RELATIVE = Path('layouts/local/site-local/layouts') / (LAYOUT + '.json')
BASE = '19aca99fc67b00219825c0f5eb45cbdbfe10611b28386e7f62aa5cb2587fa716'
LOGO = ROOT / 'static/merch_logo_chest_dark_hires.png'
WALLS = [
    dict(key='office', placement='pl-parking-office-wall-office-south',
         asset='asset-factory02-perimeter-annex-office-south', width=5.8, centerX=0, centerY=2.1, face=1),
    dict(key='cafe', placement='pl-lunchroom-wall-north',
         asset='asset-factory02-perimeter-lunch-north', width=7, centerX=-5, centerY=2, face=-1),
]


def branded_glb(dimensions, settings):
    w, d, h = (dimensions[k] for k in ('width', 'depth', 'height'))
    box = build_aabb_proxy_glb(dict(minimum=dict(x=-w/2, y=0, z=-d/2),
                                   maximum=dict(x=w/2, y=h, z=d/2)))
    size = struct.unpack_from('<I', box, 12)[0]
    doc = json.loads(box[20:20+size]); data = bytearray(box[28+size:])

    def view(payload, target=None):
        data.extend(b'\0' * (-len(data) % 4))
        result = dict(buffer=0, byteOffset=len(data), byteLength=len(payload))
        if target: result['target'] = target
        data.extend(payload); doc['bufferViews'].append(result)
        return len(doc['bufferViews'])-1

    def accessor(values, kind, count, minimum=None, maximum=None):
        result = dict(bufferView=view(struct.pack('<'+'f'*len(values), *values), 34962),
                      componentType=5126, count=count, type=kind)
        if minimum is not None: result.update(min=minimum, max=maximum)
        doc['accessors'].append(result)
        return len(doc['accessors'])-1

    # UV cropping uses the original PNG bytes; the logo itself is never edited.
    with Image.open(LOGO) as image:
        bounds = image.getchannel('A').getbbox(); iw, ih = image.size
    x0, y0, x1, y1 = bounds
    sw = settings['width']; sh = sw * (y1-y0)/(x1-x0)
    cx, cy, face = settings['centerX'], settings['centerY'], settings['face']
    assert abs(cx)+sw/2 < w/2 and 0 < cy-sh/2 < cy+sh/2 < h
    z = face*d/2
    left, right = cx-face*sw/2, cx+face*sw/2
    points = [(left, cy-sh/2, z), (right, cy-sh/2, z),
              (right, cy+sh/2, z), (left, cy+sh/2, z)]
    positions = accessor([n for p in points for n in p], 'VEC3', 4,
                         [min(p[i] for p in points) for i in range(3)],
                         [max(p[i] for p in points) for i in range(3)])
    uv = accessor([x0/iw, y1/ih, x1/iw, y1/ih, x1/iw, y0/ih, x0/iw, y0/ih], 'VEC2', 4)
    doc['accessors'].append(dict(bufferView=view(struct.pack('<6H', 0,1,2,0,2,3),34963),
                                 componentType=5123, count=6, type='SCALAR', min=[0], max=[3]))
    indices = len(doc['accessors'])-1
    doc['images'] = [dict(bufferView=view(LOGO.read_bytes()), mimeType='image/png')]
    doc['samplers'] = [dict(magFilter=9729, minFilter=9987, wrapS=33071, wrapT=33071)]
    doc['textures'] = [dict(sampler=0, source=0)]
    doc['materials'] = [dict(name='InspectorPro printed wall artwork',
        alphaMode='BLEND', doubleSided=False,
        pbrMetallicRoughness=dict(baseColorFactor=[1,1,1,1], baseColorTexture=dict(index=0),
                                  metallicFactor=0, roughnessFactor=1),
        extensions={'KHR_materials_unlit':{}}, extras=dict(facilityArtwork=True))]
    doc['extensionsUsed'] = ['KHR_materials_unlit']
    doc['meshes'].append(dict(name='InspectorPro wordmark', primitives=[dict(
        attributes=dict(POSITION=positions, TEXCOORD_0=uv), indices=indices, material=0, mode=4)]))
    doc['nodes'].append(dict(mesh=1, name='InspectorPro wordmark'))
    doc['scenes'][0]['nodes'].append(1)
    doc['asset']['generator'] = 'InspectorPro wall artwork v1'
    data.extend(b'\0' * (-len(data) % 4)); doc['buffers'][0]['byteLength'] = len(data)
    encoded = json.dumps(doc, separators=(',', ':')).encode('ascii')
    encoded += b' ' * (-len(encoded) % 4)
    result = struct.pack('<4sII', b'glTF',2,28+len(encoded)+len(data))
    result += struct.pack('<I4s', len(encoded), b'JSON') + encoded
    result += struct.pack('<I4s', len(data), b'BIN\0') + data
    evidence = inspect_glb(result).to_manifest_dict()
    assert evidence['sceneTriangleCount'] == 14
    assert LOGO.read_bytes() in result
    return result, dict(**evidence, logoSha256=hashlib.sha256(LOGO.read_bytes()).hexdigest(),
                        logoUnmodified=True, artworkWidth=sw, artworkHeight=sh,
                        face=face, centerX=cx, centerY=cy)


def audit(before, after, replacements):
    expected = deepcopy(before)
    for placement in expected['placements']:
        if placement['placementId'] in replacements:
            definition = replacements[placement['placementId']]
            placement.update(assetId=definition['assetId'],
                             assetDefinitionRevision=definition['assetDefinitionRevision'])
    expected['updatedAt'] = after['updatedAt']
    assert expected == after, 'Unexpected geometry, colors, or relationships changed'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--publish-assets', action='store_true')
    parser.add_argument('--publish-layout', action='store_true')
    parser.add_argument('--native-report', type=Path)
    args = parser.parse_args(); out = args.output.resolve()
    target = STORE / RELATIVE; manifest = ROOT / PRIVATE_ASSET_MANIFEST
    if args.publish_assets or args.publish_layout:
        report = json.loads((out / 'report.json').read_text())
        assert target.read_bytes() == (out / 'before.json').read_bytes(), 'Live Factory 02 changed'
        assert hashes(target.parent) == report['layoutHashes'], 'Saved layouts changed'
        staged = out / 'staged-project'
        if args.publish_assets:
            assert report['status'] == 'validated'
            assert manifest.read_bytes() == (out / 'catalog-before.json').read_bytes()
            for artifact in report['artifacts']:
                dest = ROOT / artifact; assert not dest.exists()
                dest.parent.mkdir(parents=True, exist_ok=True)
                RevisionedAuthorityRepository._atomic_write(dest, (staged / artifact).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest, (staged / PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status'] = 'assets-published'
        else:
            assert report['status'] == 'assets-published' and args.native_report
            assert manifest.read_bytes() == (staged / PRIVATE_ASSET_MANIFEST).read_bytes()
            for artifact in report['artifacts']:
                assert (ROOT / artifact).read_bytes() == (staged / artifact).read_bytes()
            candidate = json.loads((out / 'candidate.json').read_text())
            verify_native_candidate(json.loads(args.native_report.read_text()), candidate,
                                    (out / 'validation-store' / RELATIVE).read_bytes())
            audit(json.loads((out / 'before.json').read_text()), candidate, report['replacements'])
            host = LocalFacilityLayoutHost(STORE, private_assets=True, private_asset_root=ROOT)
            try: saved = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, BASE)
            finally: host.close()
            audit(json.loads((out / 'before.json').read_text()), saved['layout'], report['replacements'])
            others = lambda values: {k:v for k,v in values.items() if k != target.name}
            assert others(hashes(target.parent)) == others(report['layoutHashes'])
            report.update(status='saved', savedRevision=saved['revision'], otherLayoutsUnchanged=True)
            write_json(out / 'saved.json', saved['layout'])
    else:
        raw = target.read_bytes(); before = json.loads(raw)
        assert layout_revision(before) == BASE
        out.mkdir(parents=True, exist_ok=False); (out / 'before.json').write_bytes(raw)
        (out / 'catalog-before.json').write_bytes(manifest.read_bytes())
        library = json.loads(manifest.read_text()); by_id = {a['assetId']:a for a in library['assets']}
        evidence, artifacts = {}, []
        for wall in WALLS:
            spec = deepcopy(by_id[wall['asset']]); spec['assetId'] += '-inspectorpro'
            assert spec['assetId'] not in by_id
            spec['displayName'] += ' - InspectorPro'
            spec['description'] += ' Includes original InspectorPro interior wall artwork.'
            spec['artifact'] = 'generated/industrial_assets/factory02_branding/'+wall['key']+'/model.glb'
            spec['source'] = dict(kind='authored-primitive', generator=Path(__file__).name,
                                  baseAssetId=wall['asset'], logo='static/'+LOGO.name)
            data, details = branded_glb(spec['dimensions'], wall)
            dest = out / 'staged-project' / spec['artifact']; dest.parent.mkdir(parents=True)
            dest.write_bytes(data); artifacts.append(spec['artifact']); evidence[wall['key']] = details
            library['assets'].append(spec)
        library['summary']['total'] = len(library['assets'])
        write_json(out / 'staged-project' / PRIVATE_ASSET_MANIFEST, library)
        stage = out / 'validation-store'
        copytree(_native_fs_path(STORE / 'authorities'), _native_fs_path(stage / 'authorities'))
        copytree(_native_fs_path(STORE / 'layouts/local'), _native_fs_path(stage / 'layouts/local'))
        host = LocalFacilityLayoutHost(stage, private_assets=True, private_asset_root=out / 'staged-project')
        try:
            catalog = {a['assetId']:a for a in host.authoritative_asset_catalog()}
            replacements = {w['placement']:catalog[w['asset']+'-inspectorpro'] for w in WALLS}
            candidate = deepcopy(before)
            for p in candidate['placements']:
                if p['placementId'] in replacements:
                    a = replacements[p['placementId']]
                    p.update(assetId=a['assetId'], assetDefinitionRevision=a['assetDefinitionRevision'])
            audit(before, candidate, replacements)
            saved = host.service.save_layout(host.principal(), 'site-local', LAYOUT, candidate, BASE)
            audit(before, saved['layout'], replacements)
            write_json(out / 'candidate.json', saved['layout'])
            write_json(out / 'validation.json', {k:saved[k] for k in ('dependencies','spatialDiagnostics','routingDiagnostics')})
            report = dict(status='validated', baseRevision=BASE, candidateRevision=saved['revision'],
                          layoutHashes=hashes(target.parent), artifacts=artifacts, evidence=evidence,
                          replacements={pid:{k:a[k] for k in ('assetId','assetDefinitionRevision')} for pid,a in replacements.items()},
                          unchangedPlacements=len(before['placements'])-2, unchangedTransforms=True,
                          unchangedColors=True, movementPrograms=len(before['extensions']['facilityNavigation']['movementPrograms']))
        finally: host.close()
    write_json(out / 'report.json', report)
    print(json.dumps(dict(status=report['status'], revision=report.get('savedRevision',report['candidateRevision']))))


if __name__ == '__main__': main()
