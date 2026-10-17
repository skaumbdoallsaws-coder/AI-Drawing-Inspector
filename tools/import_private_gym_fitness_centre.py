"""Import the user-supplied outdoor fitness centre, weights and decorative wagon."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT=ROOT/'.runtime/private-gym-fitness-centre-import-20261009'
SOURCE=Path('C:/Users/might/OneDrive/Desktop/additional parts')
ITEMS=[('centre','Calisthenics Fitness Centre','calisthenics fitness centre.STEP'),
       ('weights','Car Assembly (Excluded: Not Gym Accessories)','assembly.STEP'),
       ('showroom','Weights and Kettlebells Showroom Assembly','SHOWROOM_ASSEMBLY.stp'),
       ('wagon','Decorative Western Wagon','WESTREN WAGON.stl')]


def convert(selected):
    OUT.mkdir(parents=True,exist_ok=True)
    items=[]
    for key,name,filename in ITEMS:
        target=base.LIBRARY/('gym-fitness-centre-'+key)
        target.mkdir(parents=True,exist_ok=True)
        source=SOURCE/filename
        if not (target/filename).exists():
            copy2(source,target/filename)
        assert base.sha(source)==base.sha(target/filename)
        item=dict(assetId='asset-gym-fitness-centre-'+key,displayName=name,source=filename,
            sourceSha256=base.sha(source),format=source.suffix.lower(),target=target.relative_to(ROOT).as_posix())
        items.append(item)
        if selected and key not in selected:
            continue
        receipt=OUT/(item['assetId']+'-conversion.json')
        if receipt.exists():
            previous=json.loads(receipt.read_text())
            assert previous['sourceSha256']==item['sourceSha256']
            if previous['status']=='converted':
                continue
        print('Converting '+name,flush=True)
        result=base.convert_stl(item) if item['format']=='.stl' else base.convert_interchange(item,True)
        result['emptyCompoundNodesRemoved']=remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted',assetId=item['assetId'],sourceSha256=item['sourceSha256'])
        base.write(receipt,result)
        print(json.dumps(result),flush=True)
    base.write(OUT/'inventory.json',items)
    if not (OUT/'orientation-review.json').exists():
        base.write(OUT/'orientation-review.json',{i['assetId']:dict(rotation=[0,0,0]) for i in items})


def prepare(selected):
    import publish_local_machine_library as publisher
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    def bounded(*args,**kwargs):
        kwargs['maximum_triangles']=min(kwargs.get('maximum_triangles',150000),150000)
        return render_software_thumbnail(*args,**kwargs)
    publisher.render_software_thumbnail=bounded
    base.OUT=OUT
    base.prepare(OUT/'orientation-review.json',{'asset-gym-fitness-centre-'+k for k in selected})
    for key,_,_ in ITEMS:
        if selected and key not in selected:
            continue
        path=base.LIBRARY/('gym-fitness-centre-'+key)/'catalog-entry.json'
        if not path.exists():
            continue
        entry=json.loads(path.read_text())
        entry['category']='Vehicles' if key=='weights' else ('Outdoor Furniture' if key=='wagon' else 'Gym Equipment')
        entry['tags']=['excluded-source-mismatch'] if key=='weights' else ['gym','outdoor','calisthenics',key]
        if key=='weights':
            entry['displayName']='Car Assembly (Excluded: Not Gym Accessories)'
            entry['description']='Source inspection identifies a car, not the requested weights. Not admitted to the library or layout.'
            entry['importReview']=dict(status='excluded',reason='Source model is a car; correct accessory file required.')
        base.write(path,entry)


def finish(selected):
    import numpy as np
    import trimesh
    from tools.apex_equipment_materials import build_variant, unpack, pack
    for key,_,_ in ITEMS:
        if key=='weights' or (selected and key not in selected):
            continue
        target=base.LIBRARY/('gym-fitness-centre-'+key)
        entry=json.loads((target/'catalog-entry.json').read_text())
        scene=trimesh.load_scene(target/'model.glb',process=False)
        overrides={}
        doc,_=unpack((target/'model.glb').read_bytes())
        if key=='showroom':
            doc,data=unpack((target/'model.glb').read_bytes())
            colors=[mat['pbrMetallicRoughness']['baseColorFactor'][:] for mat in doc['materials']]
            for mat in doc['materials']:
                mat.setdefault('extras',{})['facilityAuthoredFinish']=True
                mat['pbrMetallicRoughness'].update(metallicFactor=.15,roughnessFactor=.7)
            assert colors==[mat['pbrMetallicRoughness']['baseColorFactor'] for mat in doc['materials']]
            display=target/'model-display.glb'
            display.write_bytes(pack(doc,data))
            base.write(target/'display-mesh-evidence.json',dict(sourceSha256=base.sha(target/'model.glb'),
                displaySha256=base.sha(display),geometryPreserved=True,sourceColorsPreserved=True,
                note='Keep authored weight numbers and colour-coded plates/kettlebells intact.'))
            print('Showroom source geometry and colours preserved',flush=True)
            continue
        if key=='centre':
            roles={}
            for node in doc['nodes']:
                if 'mesh' not in node or node.get('name') not in scene.graph.nodes_geometry:
                    continue
                transform,geometry=scene.graph[node['name']]
                points=trimesh.transform_points(scene.geometry[geometry].vertices,transform)
                lo,hi=points.min(axis=0),points.max(axis=0)
                size=hi-lo
                role='gold' if size[1]<.13 and max(size[0],size[2])>.35 and lo[1]>.4 else 'frame'
                if max(size)<.14: role='steel'
                roles.setdefault(node['mesh'],set()).add(role)
            for i,mesh in enumerate(doc['meshes']):
                choices=roles.get(i,{'frame'})
                overrides[str(i)]=next(iter(choices)) if len(choices)==1 else 'frame'
        elif key=='wagon':
            # The supplied decorative wagon is a single STL without component names.
            # Reviewed height regions keep wheels dark and its timber body warm gold.
            overrides={'regions':[
                dict(role='gold_padding',bounds=[[-10,.82,-10],[10,2.7,10]])]}
        payload,evidence=build_variant(entry,overrides)
        (target/'model-display.glb').write_bytes(payload)
        base.write(target/'display-mesh-evidence.json',evidence)
        print(json.dumps(dict(assetId=entry['assetId'],triangles=evidence['triangleCount'],
            drawGroups=evidence['drawGroups'],geometryPreserved=evidence['geometryPreserved'])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','prepare','finish'])
    parser.add_argument('--key',action='append',default=[])
    args=parser.parse_args()
    if args.phase=='convert':
        convert(set(args.key))
    elif args.phase=='prepare':
        prepare(set(args.key))
    else:
        finish(set(args.key))
