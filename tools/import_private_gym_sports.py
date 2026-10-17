"""Import the supplied sports CAD, preserving units and hidden-component intent."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import struct
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from tools import import_additional_gym_assets as base

OUT = ROOT/'.runtime/private-gym-sports-20261007'
SOURCE = Path('C:/Users/might/Downloads/Video/boxing room and basketball court')
ITEMS = [('basketball-hoop', 'Wall-Mounted Basketball Hoop', 'basketball ring.stp'),
         ('boxing-ring', 'Boxing Ring', 'boxing ring.stp'),
         ('boxing-bag', 'Wall-Mounted Boxing Bag', 'Boxing bag.SLDASM')]


def remove_empty_cad_nodes(path):
    raw = path.read_bytes()
    size = struct.unpack_from('<I', raw, 12)[0]
    document = json.loads(raw[20:20+size])
    empty = []
    for index, mesh in enumerate(document['meshes']):
        primitives = mesh['primitives']
        invalid = [p for p in primitives if p.get('attributes', {}).get('POSITION') == -1 and p.get('indices') == -1]
        if invalid:
            assert len(invalid) == len(primitives), 'Mixed malformed and valid CAD primitives'
            empty.append(index)
    if not empty: return []
    remap = {old:new for new,old in enumerate(i for i in range(len(document['meshes'])) if i not in empty)}
    for node in document['nodes']:
        if node.get('mesh') in empty: del node['mesh']
        elif 'mesh' in node: node['mesh'] = remap[node['mesh']]
    document['meshes'] = [m for i,m in enumerate(document['meshes']) if i not in empty]
    data = json.dumps(document, separators=(',', ':')).encode()
    data += b' '*((-len(data))%4)
    tail = raw[20+size:]
    path.write_bytes(struct.pack('<III',0x46546c67,2,20+len(data)+len(tail))+
                     struct.pack('<II',len(data),0x4e4f534a)+data+tail)
    return empty


def convert_bag(target):
    import numpy as np
    import trimesh
    evidence = json.loads((target/'visible-meshes.json').read_text(encoding='utf-8-sig'))
    scene = trimesh.Scene()
    for component in evidence['included']:
        t = np.asarray(component['transform'])
        matrix = np.eye(4); matrix[:3,:3] = t[:9].reshape(3,3).T*t[12]; matrix[:3,3] = t[9:12]
        for index, body in enumerate(component['meshes']):
            vertices = np.asarray(body.pop('vertices')).reshape(-1,3)
            assert np.isfinite(vertices).all() and len(vertices)%3 == 0
            mesh = trimesh.Trimesh(vertices=vertices, faces=np.arange(len(vertices)).reshape(-1,3), process=False)
            mesh.apply_transform(matrix)
            mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
                baseColorFactor=[143,39,43,255] if 'bag' in component['name'].rsplit('/',1)[-1].lower() else [70,78,85,255],
                metallicFactor=.05, roughnessFactor=.75, doubleSided=body['sheet']))
            scene.add_geometry(mesh, node_name=component['name']+'-'+str(index))
            body['triangles'] = len(mesh.faces)
    (target/'model.glb').write_bytes(scene.export(file_type='glb'))
    base.write(target/'native-export.json', evidence)
    return dict(artifact=(target/'model.glb').relative_to(ROOT).as_posix(), nativeEvidence=evidence,
                units=dict(sourceUnits='m', authority='SolidWorks_API_meters'))


def convert():
    OUT.mkdir(parents=True, exist_ok=True)
    inventory = []
    for key, name, filename in ITEMS:
        target = base.LIBRARY/('gym-sports-'+key)
        target.mkdir(parents=True, exist_ok=True)
        if not (target/filename).exists(): shutil.copy2(SOURCE/filename, target/filename)
        assert base.sha(target/filename) == base.sha(SOURCE/filename)
        item = dict(assetId='asset-gym-sports-'+key, displayName=name, source=filename,
                    sourceSha256=base.sha(SOURCE/filename), format=Path(filename).suffix.lower(),
                    target=target.relative_to(ROOT).as_posix())
        inventory.append(item)
        receipt = OUT/(item['assetId']+'-conversion.json')
        if receipt.exists():
            result = json.loads(receipt.read_text())
            removed = remove_empty_cad_nodes(ROOT/result['artifact'])
            if removed:
                result['emptyCompoundNodesRemoved'] = removed
                base.write(receipt, result)
            continue
        if key == 'boxing-bag':
            result = convert_bag(target)
        else: result = base.convert_interchange(item)
        result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted', assetId=item['assetId'], sourceSha256=item['sourceSha256'])
        base.write(receipt, result)
        print(json.dumps(dict(assetId=item['assetId'],status=result['status'],artifact=result['artifact'])), flush=True)
    base.write(OUT/'inventory.json', inventory)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'prepare'])
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    if args.phase == 'convert': convert()
    else:
        base.OUT = OUT
        base.prepare(args.review, set())
