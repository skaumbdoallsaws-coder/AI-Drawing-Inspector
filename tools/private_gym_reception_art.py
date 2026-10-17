"""Revision-bound replacement of only Private Gym's reception feature wall."""
from copy import deepcopy
import argparse
import hashlib
import json
from pathlib import Path
from shutil import copytree
import struct
import sys
import uuid

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from ai_inspector.facility_layout.authority_repository import RevisionedAuthorityRepository, _native_fs_path
from ai_inspector.facility_layout.canonical import layout_revision
from ai_inspector.facility_layout.host import LocalFacilityLayoutHost, PRIVATE_ASSET_MANIFEST
from ai_inspector.industrial_assets.artifacts import build_aabb_proxy_glb, inspect_glb
from tools.build_private_gym import LAYOUT, STORE, IDENTITY, write
from tools.add_factory02_parking_office import hashes

OUT=ROOT/'.runtime/private-gym-reception-art-20261007'
ASSET='asset-private-gym-reception-congo-mural'
ARTIFACT='generated/industrial_assets/private_gym/reception-congo/model.glb'
TEXTURE=ROOT/'generated/industrial_assets/private_gym/reception-congo/mural.png'
ORIGINAL=Path('C:/Users/might/Downloads/congo_leopard_flag_square_7200px (1).png')
RELATIVE=Path('layouts/local/site-local/layouts')/(LAYOUT+'.json')


def artwork_bounds(width,height,dimensions,fit='full'):
    w,h=dimensions['width'],dimensions['height']
    assert fit in ('full','contain')
    if fit=='full':
        assert abs(width/height-w/h)<.01,'Mural must match the wall aspect ratio'
        return -w/2,0,w/2,h
    scale=min((w-.2)/width,(h-.2)/height)
    assert scale>0
    aw,ah=width*scale,height*scale
    return -aw/2,(h-ah)/2,aw/2,(h+ah)/2


def wall_glb(png,dimensions,*,fit='full',face=1,name='Congo reception mural'):
    w,d,h=[dimensions[k] for k in ('width','depth','height')]
    assert png.startswith(b'\x89PNG\r\n\x1a\n')
    width,height=struct.unpack('>II',png[16:24])
    x0,y0,x1,y1=artwork_bounds(width,height,dimensions,fit)
    assert face in (-1,1)
    raw=build_aabb_proxy_glb(dict(minimum=dict(x=-w/2,y=0,z=-d/2),maximum=dict(x=w/2,y=h,z=d/2)))
    size=struct.unpack_from('<I',raw,12)[0]
    doc=json.loads(raw[20:20+size]);data=bytearray(raw[28+size:])
    def view(payload,target=None):
        data.extend(b'\0'*(-len(data)%4))
        v=dict(buffer=0,byteOffset=len(data),byteLength=len(payload))
        if target:v['target']=target
        data.extend(payload);doc['bufferViews'].append(v)
        return len(doc['bufferViews'])-1
    def floats(values,kind,count,minimum=None,maximum=None):
        a=dict(bufferView=view(struct.pack('<'+'f'*len(values),*values),34962),componentType=5126,count=count,type=kind)
        if minimum is not None:a.update(min=minimum,max=maximum)
        doc['accessors'].append(a);return len(doc['accessors'])-1
    # Reverse both winding and horizontal mapping for the back-facing wall art.
    left,right=(x0,x1) if face==1 else (x1,x0)
    z=face*d/2
    pos=floats([left,y0,z,right,y0,z,right,y1,z,left,y1,z], 'VEC3',4,[x0,y0,z],[x1,y1,z])
    uv=floats([0,1,1,1,1,0,0,0],'VEC2',4)
    doc['accessors'].append(dict(bufferView=view(struct.pack('<6H',0,1,2,0,2,3),34963),componentType=5123,count=6,type='SCALAR',min=[0],max=[3]))
    indices=len(doc['accessors'])-1
    doc['images']=[dict(bufferView=view(png),mimeType='image/png')]
    doc['samplers']=[dict(magFilter=9729,minFilter=9987,wrapS=33071,wrapT=33071)]
    doc['textures']=[dict(sampler=0,source=0)]
    materials=doc.setdefault('materials',[])
    index=len(materials)
    materials.append(dict(name=name,alphaMode='BLEND' if fit=='contain' else 'OPAQUE',doubleSided=False,
        pbrMetallicRoughness=dict(baseColorFactor=[1,1,1,1],baseColorTexture=dict(index=0),metallicFactor=0,roughnessFactor=1),
        extensions={'KHR_materials_unlit':{}},extras=dict(facilityArtwork=True)))
    doc['extensionsUsed']=['KHR_materials_unlit']
    mesh_index=len(doc['meshes'])
    doc['meshes'].append(dict(name='Full-wall mural',primitives=[dict(attributes=dict(POSITION=pos,TEXCOORD_0=uv),indices=indices,material=index,mode=4)]))
    node_index=len(doc['nodes']);doc['nodes'].append(dict(mesh=mesh_index,name='Full-wall mural'))
    doc['scenes'][0]['nodes'].append(node_index)
    doc['asset']['generator']='InspectorPro full-wall artwork'
    data.extend(b'\0'*(-len(data)%4));doc['buffers'][0]['byteLength']=len(data)
    encoded=json.dumps(doc,separators=(',',':')).encode('ascii');encoded+=b' '*(-len(encoded)%4)
    result=struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(data))+struct.pack('<I4s',len(encoded),b'JSON')+encoded+struct.pack('<I4s',len(data),b'BIN\0')+data
    assert inspect_glb(result).to_manifest_dict()['sceneTriangleCount']==14
    assert png in result
    return result


def audit(before,after,pid,definition):
    expected=deepcopy(before)
    wall=next(p for p in expected['placements'] if p['placementId']==pid)
    wall.update(assetId=definition['assetId'],assetDefinitionRevision=definition['assetDefinitionRevision'])
    expected['updatedAt']=after['updatedAt']
    assert expected==after,'Content beyond the reception artwork changed'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--publish-assets',action='store_true')
    parser.add_argument('--save',action='store_true')
    args=parser.parse_args();target=STORE/RELATIVE;manifest=ROOT/PRIVATE_ASSET_MANIFEST
    if args.save:
        report=json.loads((OUT/'report.json').read_text())
        native=json.loads((OUT/'native-check.json').read_text())
        before=json.loads((OUT/'before.json').read_text());candidate=json.loads((OUT/'candidate.json').read_text())
        assert native['status']=='preview-verified'
        assert native['candidateHash']==hashlib.sha256((OUT/'candidate.json').read_bytes()).hexdigest()
        assert target.read_bytes()==(OUT/'before.json').read_bytes(),'Saved gym changed'
        assert manifest.read_bytes()==(OUT/'staged-project'/PRIVATE_ASSET_MANIFEST).read_bytes()
        assert (ROOT/ARTIFACT).read_bytes()==(OUT/'staged-project'/ARTIFACT).read_bytes()
        audit(before,candidate,report['placementId'],report['replacement'])
        host=LocalFacilityLayoutHost(STORE,private_assets=True,private_asset_root=ROOT)
        try:saved=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,report['baseRevision'])
        finally:host.close()
        audit(before,saved['layout'],report['placementId'],report['replacement'])
        assert all(v==hashes(target.parent)[k] for k,v in report['layoutHashes'].items() if k not in (target.name,'registry.json'))
        write(OUT/'saved.json',saved['layout'])
        report.update(status='saved',savedRevision=saved['revision'],otherLayoutsUnchanged=True)
        write(OUT/'report.json',report)
        print(json.dumps(dict(status=report['status'],savedRevision=saved['revision'])))
        return
    OUT.mkdir(parents=True,exist_ok=True)
    raw=target.read_bytes();before=json.loads(raw)
    catalog_bytes=manifest.read_bytes()
    for name,payload in [('before.json',raw),('catalog-before.json',catalog_bytes)]:
        snapshot=OUT/name
        if snapshot.exists():assert snapshot.read_bytes()==payload,'Source changed since staging began: '+name
        else:snapshot.write_bytes(payload)
    library=json.loads(catalog_bytes)
    wall=next(p for p in before['placements'] if p['assetId']=='asset-private-gym-reception-brand')
    old=next(a for a in library['assets'] if a['assetId']==wall['assetId'])
    assert not any(a['assetId']==ASSET for a in library['assets'])
    png=TEXTURE.read_bytes();payload=wall_glb(png,old['dimensions'])
    spec=dict(assetId=ASSET,displayName='Private Gym Reception - Congo Mural',category='Building Structures',
        dimensions=old['dimensions'],sourceToCanonical=IDENTITY,artifact=ARTIFACT,tags=['wall','gym','artwork'],
        description='Full-height widescreen adaptation of user-provided Congo artwork. Same reception-wall geometry.',
        source=dict(kind='authored-textured-wall',originalFile=ORIGINAL.name,originalSha256=hashlib.sha256(ORIGINAL.read_bytes()).hexdigest(),
            muralSha256=hashlib.sha256(png).hexdigest(),adaptation='Built-in image generation: extend square flag composition to 80:33. Original retained.'))
    library['assets'].append(spec);library['summary']['total']=len(library['assets'])
    staged=OUT/'staged-project';art=staged/ARTIFACT;art.parent.mkdir(parents=True,exist_ok=True);art.write_bytes(payload)
    write(staged/PRIVATE_ASSET_MANIFEST,library)
    stage=OUT/'validation-store'
    copytree(_native_fs_path(STORE/'authorities'),_native_fs_path(stage/'authorities'),dirs_exist_ok=True)
    copytree(_native_fs_path(STORE/'layouts/local'),_native_fs_path(stage/'layouts/local'),dirs_exist_ok=True)
    host=LocalFacilityLayoutHost(stage,private_assets=True,private_asset_root=staged)
    try:
        definition=next(a for a in host.authoritative_asset_catalog() if a['assetId']==ASSET)
        replacement={k:definition[k] for k in ('assetId','assetDefinitionRevision')}
        candidate=deepcopy(before)
        next(p for p in candidate['placements'] if p['placementId']==wall['placementId']).update(replacement)
        audit(before,candidate,wall['placementId'],replacement)
        result=host.service.save_layout(host.principal(),'site-local',LAYOUT,candidate,layout_revision(before))
        candidate=result['layout'];audit(before,candidate,wall['placementId'],replacement)
    finally:host.close()
    write(OUT/'candidate.json',candidate)
    report=dict(status='validated',baseRevision=layout_revision(before),candidateRevision=layout_revision(candidate),
        placementId=wall['placementId'],replacement=replacement,layoutHashes=hashes(target.parent),
        unchangedPlacements=len(before['placements'])-1,unchangedGeometry=True,wallSizeMeters=old['dimensions'])
    if args.publish_assets:
        assert manifest.read_bytes()==catalog_bytes and target.read_bytes()==raw
        dest=ROOT/ARTIFACT;assert not dest.exists()
        RevisionedAuthorityRepository._atomic_write(dest,payload)
        RevisionedAuthorityRepository._atomic_write(manifest,(staged/PRIVATE_ASSET_MANIFEST).read_bytes())
        report['status']='assets-published'
    write(OUT/'report.json',report)
    profile=json.loads((ROOT/'.runtime/private-gym-detail-20261007/profile.json').read_text())
    profile.update(profileId='private-gym-art-review',origin='http://127.0.0.1:8538',dataRoot=str(OUT),
        backendId=str(uuid.uuid4()),storeId=str(uuid.uuid4()))
    write(OUT/'profile.json',profile)
    print(json.dumps({k:report[k] for k in ('status','baseRevision','candidateRevision','placementId','unchangedPlacements')}))


if __name__=='__main__':main()
