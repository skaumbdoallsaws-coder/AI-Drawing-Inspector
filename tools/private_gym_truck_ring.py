"""Scope-checked Ford finish, ring branding and outdoor goal removal."""
from copy import deepcopy
from io import BytesIO
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import struct
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(Path.home()/'AppData/Roaming/Python/Python314/site-packages')]
from tools.apex_equipment_materials import build_variant, pack, unpack, np, trimesh
from tools.build_private_gym import LAYOUT, STORE, write, saved_hashes
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST

OUT = ROOT/'.runtime/private-gym-truck-ring-20261008'
REMOVED = {'pl-private-gym-fields-training-goal', 'pl-private-gym-fields-drill-ball'}
PICKUP = 'pl-private-gym-fields-pickup'
RING = 'pl-private-gym-sports-boxing-ring'
LOGO = ROOT/'generated/industrial_assets/private_gym/apex-court/back/branding-only/centered/apex-logo.png'
FORD = {
    '0': 'vehicle_paint', '1': 'frame', '6': 'gold',
    **{str(i): 'rubber' for i in range(2, 6)},
    'regions': [dict(bounds=[[-1.02, .1, z-.28], [1.02, .65, z+.28]],
                     cylinder=dict(axis=0, center=[0, .375, z], radius=.238),
                     sourceRole='rubber', role='gold') for z in [-1.5434, 1.6716]],
    'connectedComponents': [
        dict(mesh='F150', faces=3460, bounds=[[-.85636, 1.38603, -.52841], [.85637, 1.9257, -.43439]], role='smoked_glass'),
        dict(mesh='F150', faces=4906, bounds=[[-.86861, 1.39591, .47983], [.86861, 1.89085, 1.33215]], role='smoked_glass'),
        dict(mesh='F150', faces=924, bounds=[[.73492, 1.37998, -.36004], [.95194, 1.91404, -.24888]], role='smoked_glass'),
        dict(mesh='F150', faces=924, bounds=[[-.95194, 1.37998, -.36012], [-.73492, 1.91404, -.24888]], role='smoked_glass'),
        dict(mesh='F150', faces=1370, bounds=[[.53779, .77573, 2.08547], [.93122, 1.14304, 2.5173]], role='marking'),
        dict(mesh='F150', faces=1342, bounds=[[-.93122, .77573, 2.08547], [-.53779, 1.14304, 2.5173]], role='marking'),
        dict(mesh='F150', faces=15984, bounds=[[-.99628, .41342, 2.13396], [.99628, .71317, 2.6584]], role='steel'),
        dict(mesh='F150', faces=14022, bounds=[[-.72811, .72852, 2.36931], [.72811, 1.15247, 2.61838]], role='gold'),
    ],
}


def ring_logo(raw, canonical, png):
    """Append a centered textured plane without altering existing CAD buffers."""
    assert png[:8] == b'\x89PNG\r\n\x1a\n'
    width, height = struct.unpack('>II', png[16:24])
    w, d = 4.6, 4.6*height/width
    assert d < 5.5
    doc, original = unpack(raw)
    data = bytearray(original)

    def view(payload, target=None):
        data.extend(b'\0'*(-len(data) % 4))
        item = dict(buffer=0, byteOffset=len(data), byteLength=len(payload))
        if target: item['target'] = target
        data.extend(payload)
        doc['bufferViews'].append(item)
        return len(doc['bufferViews'])-1

    def accessor(values, kind, count, minimum, maximum):
        doc['accessors'].append(dict(bufferView=view(struct.pack('<'+'f'*len(values), *values), 34962),
            componentType=5126, count=count, type=kind, min=minimum, max=maximum))
        return len(doc['accessors'])-1

    y = 1.003
    pos = accessor([-w/2,y,d/2, w/2,y,d/2, w/2,y,-d/2, -w/2,y,-d/2],
                   'VEC3', 4, [-w/2,y,-d/2], [w/2,y,d/2])
    normal = accessor([0,1,0]*4, 'VEC3', 4, [0,1,0], [0,1,0])
    uv = accessor([0,1, 1,1, 1,0, 0,0], 'VEC2', 4, [0,0], [1,1])
    doc['accessors'].append(dict(bufferView=view(struct.pack('<6H',0,1,2,0,2,3),34963),
        componentType=5123,count=6,type='SCALAR',min=[0],max=[3]))
    indices = len(doc['accessors'])-1
    image_index = len(doc.setdefault('images', []))
    doc['images'].append(dict(bufferView=view(png),mimeType='image/png'))
    sampler = len(doc.setdefault('samplers', []))
    doc['samplers'].append(dict(magFilter=9729,minFilter=9987,wrapS=33071,wrapT=33071))
    texture = len(doc.setdefault('textures', []))
    doc['textures'].append(dict(sampler=sampler,source=image_index))
    material = len(doc.setdefault('materials', []))
    doc['materials'].append(dict(name='APEX canvas logo',alphaMode='BLEND',doubleSided=False,
        extras=dict(facilityArtwork=True),extensions={'KHR_materials_unlit':{}},
        pbrMetallicRoughness=dict(baseColorFactor=[1,1,1,1],baseColorTexture=dict(index=texture),
                                 metallicFactor=0,roughnessFactor=1)))
    doc['extensionsUsed'] = sorted(set(doc.get('extensionsUsed', [])+['KHR_materials_unlit']))
    mesh = len(doc['meshes'])
    doc['meshes'].append(dict(name='Centered APEX canvas logo',primitives=[dict(
        attributes=dict(POSITION=pos,NORMAL=normal,TEXCOORD_0=uv),indices=indices,material=material,mode=4)]))
    node = len(doc['nodes'])
    inverse = np.linalg.inv(np.array(canonical).reshape(4,4,order='F'))
    doc['nodes'].append(dict(name='Centered APEX canvas logo',mesh=mesh,matrix=inverse.flatten(order='F').tolist()))
    doc['scenes'][doc.get('scene',0)]['nodes'].append(node)
    doc['buffers'][0]['byteLength'] = len(data)
    result = pack(doc,bytes(data))
    prior = trimesh.load(BytesIO(raw),file_type='glb',force='scene',process=False)
    after = trimesh.load(BytesIO(result),file_type='glb',force='scene',process=False)
    assert np.allclose(prior.bounds,after.bounds,atol=2e-6,rtol=0)
    assert unpack(result)[1][:len(original)] == original
    return result, dict(logoSha256=hashlib.sha256(png).hexdigest(),widthMeters=w,depthMeters=d,
                        centerCanonical=[0,y,0],originalGeometryBuffersUnchanged=True,addedTriangles=2,
                        envelopeUnchanged=True)


def change_document(before, replacements):
    assert set(replacements)=={PICKUP,RING}
    assert REMOVED <= {p['placementId'] for p in before['placements']}
    candidate=deepcopy(before)
    candidate['placements']=[p for p in candidate['placements'] if p['placementId'] not in REMOVED]
    for p in candidate['placements']:
        if p['placementId'] in replacements:p.update(replacements[p['placementId']])
    assert not any(pid in json.dumps(candidate) for pid in REMOVED), 'Deleted placement still referenced'
    return candidate


def audit(before,after,replacements):
    expected=change_document(before,replacements)
    expected['updatedAt']=after['updatedAt']
    assert expected==after, 'Unexpected layout change'


def main(phase):
    OUT.mkdir(parents=True,exist_ok=True)
    target=STORE/'layouts/local/site-local/layouts'/(LAYOUT+'.json')
    manifest=ROOT/PRIVATE_ASSET_MANIFEST
    staged=OUT/'staged-project'
    if phase!='stage':
        report=json.loads((OUT/'report.json').read_text())
        assert target.read_bytes()==(OUT/'before.json').read_bytes(), 'Saved gym changed'
        if phase=='publish':
            assert manifest.read_bytes()==(OUT/'catalog-before.json').read_bytes(), 'Library changed'
            for relative in report['artifacts']:assert not (ROOT/relative).exists()
            for relative in report['artifacts']:
                RevisionedAuthorityRepository._atomic_write(ROOT/relative,(staged/relative).read_bytes())
            RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
            report['status']='assets-published'
        else:
            native=json.loads((OUT/'native-check.json').read_text())
            raw=(OUT/'candidate.json').read_bytes()
            assert native['status']=='preview-verified' and native['candidateHash']==hashlib.sha256(raw).hexdigest()
            assert manifest.read_bytes()==(staged/PRIVATE_ASSET_MANIFEST).read_bytes()
            for relative in report['artifacts']:assert (ROOT/relative).read_bytes()==(staged/relative).read_bytes()
            before=json.loads((OUT/'before.json').read_bytes());candidate=json.loads(raw)
            audit(before,candidate,report['replacements'])
            host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
            try:receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
            finally:host.close()
            audit(before,receipt['layout'],report['replacements'])
            write(OUT/'saved.json',receipt['layout'])
            after=saved_hashes()
            assert all(after[k]==v for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
            report.update(status='saved',savedRevision=receipt['revision'],otherLayoutsUnchanged=True)
        write(OUT/'report.json',report);print(report['status']);return
    before_raw=target.read_bytes();catalog_raw=manifest.read_bytes()
    before=json.loads(before_raw);library=json.loads(catalog_raw)
    for name,raw in [('before.json',before_raw),('catalog-before.json',catalog_raw)]:
        p=OUT/name
        if p.exists():assert p.read_bytes()==raw,'Staging source changed'
        else:p.write_bytes(raw)
    artifacts=[];checks=[];bindings={}
    for pid,suffix in [(PICKUP,'apex'),(RING,'branded')]:
        placement=next(p for p in before['placements'] if p['placementId']==pid)
        old=next(a for a in library['assets'] if a['assetId']==placement['assetId'])
        new=deepcopy(old);new['assetId']=old['assetId']+'-'+suffix
        assert not any(a['assetId']==new['assetId'] for a in library['assets'])
        if pid==PICKUP:
            payload,evidence=build_variant(old,FORD)
            new['displayName']='Ford F-150 Pickup - APEX Black and Gold'
            new['visualImport']={k:v for k,v in evidence.items() if k!='components'}
            new['measuredGeometry'].update(sourceSha256=evidence['displaySha256'],triangles=evidence['triangleCount'])
        else:
            payload,evidence=ring_logo((ROOT/old['artifact']).read_bytes(),old['sourceToCanonical'],LOGO.read_bytes())
            new['displayName']='Boxing Ring - APEX Center Branding'
            new['visualImport']=dict(source=(old['artifact']),sourceSha256=hashlib.sha256((ROOT/old['artifact']).read_bytes()).hexdigest(),
                                      displaySha256=hashlib.sha256(payload).hexdigest(),**evidence)
            if 'measuredGeometry' in new:
                new['measuredGeometry'].update(sourceSha256=new['visualImport']['displaySha256'],
                    triangles=new['measuredGeometry']['triangles']+2)
        relative='generated/industrial_assets/private_gym/truck-ring/'+new['assetId']+'/model.glb'
        dest=staged/relative;dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(payload)
        new['artifact']=relative;new['description']=old.get('description','')+' APEX display variant; original CAD preserved.'
        library['assets'].append(new);artifacts.append(relative);bindings[pid]=new['assetId'];checks.append(evidence)
    library['summary']['total']=len(library['assets']);write(staged/PRIVATE_ASSET_MANIFEST,library)
    stage=OUT/'validation-store'
    for rel in ['authorities','layouts/local']:
        copytree(_native_fs_path(STORE/rel),_native_fs_path(stage/rel),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        catalog={a['assetId']:a for a in host.authoritative_asset_catalog()}
        replacements={pid:{k:catalog[aid][k] for k in ('assetId','assetDefinitionRevision')} for pid,aid in bindings.items()}
        candidate=change_document(before,replacements)
        receipt=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
        audit(before,receipt['layout'],replacements)
    finally:host.close()
    write(OUT/'candidate.json',receipt['layout'])
    write(OUT/'report.json',dict(status='validated',baseRevision=layout_revision(before),
        replacements=replacements,removed=sorted(REMOVED),artifacts=artifacts,checks=checks,layoutHashes=saved_hashes()))
    profile=json.loads((ROOT/'.runtime/private-gym-equipment-theme-20261008/sports/profile.json').read_text())
    profile.update(profileId='private-gym-truck-ring',origin='http://127.0.0.1:8557',dataRoot=str(OUT),
                   backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    def shot(name,p,t):
        return dict(name=name,position=dict(zip('xyz',p)),target=dict(zip('xyz',t)),thresholds=dict(detail=1000))
    shots=[shot('ford-front',(83,3.2,51),(78,1,45)),shot('cleared-outdoor-area',(53,6,61),(48.5,0,67)),
           shot('ring-logo-overhead',(69.2,12,8.1),(69.2,1,8)),shot('ring-logo-oblique',(75.8,5.5,14),(69.2,1,8))]
    write(OUT/'review-config.json',dict(profileId=profile['profileId'],requiredAssets=list(bindings.values()),
        minimumAssetMeshes=2,shots=shots,finalShot={**shots[-1],'name':'saved-ring-branding'}))
    print(json.dumps(dict(status='validated',placements=len(receipt['layout']['placements']),removed=sorted(REMOVED))))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['stage','publish','save'])
    main(parser.parse_args().phase)
