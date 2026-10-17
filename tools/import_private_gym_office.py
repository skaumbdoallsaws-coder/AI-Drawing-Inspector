"""Import and measure the owner's office set and two alternative bookshelves."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT=ROOT/'.runtime/private-gym-office-import-20261008'
SOURCE=Path('C:/Users/might/Downloads')
ITEMS=[('set','Office Furniture Set','off1ce room set 3004202502.stl'),
       ('bookshelf-2','Bookshelf 2','bookshelf 2.STEP'),
       ('book-shelf','Book Shelf','Book Shelf STEP.STEP')]


def normalize():
    import numpy as np
    import trimesh
    folder=base.LIBRARY/'gym-office-set'
    mesh=trimesh.load_mesh(folder/ITEMS[0][2],process=False)
    # This source's separate 4 m square presentation plane is not furniture.
    floor=np.all(np.abs(mesh.triangles[:,:,2]+38.17966842651367)<1e-5,axis=1)
    assert int(floor.sum())==800
    vertices=mesh.triangles[floor].reshape(-1,3)
    assert np.allclose(np.ptp(vertices,axis=0),[400,400,0],atol=1e-4)
    mesh.update_faces(~floor);mesh.remove_unreferenced_vertices();mesh.apply_scale(.01)
    assert len(mesh.faces)==544540
    mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[53,57,62,255],metallicFactor=.1,roughnessFactor=.65,doubleSided=True))
    dest=folder/'model-display.glb';dest.write_bytes(mesh.export(file_type='glb'))
    base.write(folder/'display-mesh-evidence.json',dict(sourceSha256=base.sha(folder/ITEMS[0][2]),
        removedPresentationPlaneTriangles=800,furnitureTriangles=544540,displaySha256=base.sha(dest),
        furnitureGeometryPreserved=True))
    base.write(OUT/'orientation-review.json',{
        'asset-gym-office-set':dict(rotation=[-90,0,0],note='Source presentation floor omitted in display copy; furniture geometry retained.'),
        'asset-gym-office-bookshelf-2':dict(rotation=[0,0,180],note='Corrected upside-down source orientation; feet and doors verified visually.'),
        'asset-gym-office-book-shelf':dict(rotation=[0,0,0],name='Miniature Book Shelf - Scale Review Required',note='Only 220 mm tall in source CAD units; not selected for furnishing.')})


def convert():
    OUT.mkdir(parents=True,exist_ok=True)
    items=[]
    for key,name,filename in ITEMS:
        target=base.LIBRARY/('gym-office-'+key);target.mkdir(parents=True,exist_ok=True)
        source=SOURCE/filename
        if not (target/filename).exists():copy2(source,target/filename)
        assert base.sha(source)==base.sha(target/filename)
        item=dict(assetId='asset-gym-office-'+key,displayName=name,source=filename,
                  sourceSha256=base.sha(source),format=source.suffix.lower(),target=target.relative_to(ROOT).as_posix())
        items.append(item)
        receipt=OUT/(item['assetId']+'-conversion.json')
        if receipt.exists():
            previous=json.loads(receipt.read_text())
            assert previous['sourceSha256']==item['sourceSha256']
            if previous['status']=='converted':continue
        result=base.convert_stl(item) if item['format']=='.stl' else base.convert_interchange(item,True)
        result['emptyCompoundNodesRemoved']=remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted',assetId=item['assetId'],sourceSha256=item['sourceSha256'])
        base.write(receipt,result)
        print(json.dumps(result),flush=True)
    base.write(OUT/'inventory.json',items)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','normalize','prepare'])
    parser.add_argument('--review',type=Path)
    args=parser.parse_args()
    if args.phase=='convert':convert()
    elif args.phase=='normalize':normalize()
    else:
        base.OUT=OUT
        base.prepare(args.review,set())
        for key,*_ in ITEMS:
            path=base.LIBRARY/('gym-office-'+key)/'catalog-entry.json'
            entry=json.loads(path.read_text())
            entry['description']=entry['description'].replace('gym equipment','office furniture').replace(
                'exercise clearances, installation requirements and load ratings','ergonomic clearances, installation requirements and load ratings')
            entry['tags']=['office','furniture',key]
            base.write(path,entry)
