"""Import the supplied wall bars and push-up supports at their STEP unit scale."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT=ROOT/'.runtime/private-gym-calisthenics-import-20261009'
SOURCE=Path('C:/Users/might/OneDrive/Desktop/additional parts')
ITEMS=[('wall-bar','Wall-Mounted Pull-Up Bar','WALL-MOUNTED PULL-UP BAR.stp'),
       ('pushup-supports','Calisthenics Push-Up Supports','calisthenics pushup supports.stp')]


def convert():
    OUT.mkdir(parents=True,exist_ok=True)
    items=[]
    for key,name,filename in ITEMS:
        target=base.LIBRARY/('gym-calisthenics-'+key)
        target.mkdir(parents=True,exist_ok=True)
        source=SOURCE/filename
        if not (target/filename).exists():
            copy2(source,target/filename)
        assert base.sha(source)==base.sha(target/filename)
        item=dict(assetId='asset-gym-calisthenics-'+key,displayName=name,source=filename,
            sourceSha256=base.sha(source),format='.stp',target=target.relative_to(ROOT).as_posix())
        items.append(item)
        receipt=OUT/(item['assetId']+'-conversion.json')
        if receipt.exists():
            previous=json.loads(receipt.read_text())
            assert previous['sourceSha256']==item['sourceSha256']
            if previous['status']=='converted':
                continue
        result=base.convert_interchange(item,True)
        result['emptyCompoundNodesRemoved']=remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted',assetId=item['assetId'],sourceSha256=item['sourceSha256'])
        base.write(receipt,result)
        print(json.dumps(result),flush=True)
    base.write(OUT/'inventory.json',items)
    if not (OUT/'orientation-review.json').exists():
        base.write(OUT/'orientation-review.json',{i['assetId']:dict(rotation=[0,0,0]) for i in items})


def prepare():
    base.OUT=OUT
    base.prepare(OUT/'orientation-review.json',set())
    for key,_,_ in ITEMS:
        path=base.LIBRARY/('gym-calisthenics-'+key)/'catalog-entry.json'
        entry=json.loads(path.read_text())
        entry['category']='Gym Equipment'
        entry['tags']=['gym','calisthenics','outdoor',key]
        base.write(path,entry)


def finish():
    from tools.apex_equipment_materials import unpack, pack, material
    for key,_,_ in ITEMS:
        target=base.LIBRARY/('gym-calisthenics-'+key)
        doc,data=unpack((target/'model.glb').read_bytes())
        geometry=[(p['attributes'],p.get('indices')) for m in doc['meshes'] for p in m['primitives']]
        doc['materials']=[material('gold' if key=='wall-bar' else 'frame')]
        for mesh in doc['meshes']:
            for primitive in mesh['primitives']:
                primitive['material']=0
        assert geometry==[(p['attributes'],p.get('indices')) for m in doc['meshes'] for p in m['primitives']]
        display=target/'model-display.glb'
        display.write_bytes(pack(doc,data))
        base.write(target/'display-mesh-evidence.json',dict(sourceSha256=base.sha(target/'model.glb'),
            displaySha256=base.sha(display),geometryUnchanged=True,
            finish='Metallic Gold #C99B39' if key=='wall-bar' else 'Matte Black #17191C'))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','finish','prepare'])
    args=parser.parse_args()
    {'convert':convert,'finish':finish,'prepare':prepare}[args.phase]()
