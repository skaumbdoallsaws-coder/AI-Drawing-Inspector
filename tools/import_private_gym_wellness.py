"""Import the owner's lounge, recovery and washroom CAD with reviewable units."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import struct
import sys
import traceback

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT=ROOT/'.runtime/private-gym-wellness-import-20261008'
SOURCE=Path('C:/Users/might/Downloads')
ITEMS=[
 ('unknown-seat','Unidentified Furniture','not sure','stl.STL'),
 ('drawer','Storage Drawer','not sure','\u00e7orap \u00e7ekmecesi 2209202502.stl'),
 ('massage-chair','Massage Chair','recovery room','final massage chair.igs'),
 ('massage-table','Massage Table','recovery room','massage couch.STEP'),
 ('arcade','Arcade Cabinet','social lounge','Arcade.STEP'),
 ('chess-set','Chess Set','social lounge','chess set.STL'),
 ('chess-pieces','Chess Pieces','social lounge','chessboard.STL'),
 ('foosball','Foosball Table','social lounge','football table game.STEP'),
 ('folding-pingpong','Folding Table Tennis Table','social lounge','pingpong table.stl'),
 ('sideboard','Lounge Sideboard','social lounge','silver ware cabinet 0809202401.stl'),
 ('sofa','Lounge Sofa','social lounge','SOFA 2609202402.stl'),
 ('piano','Grand Piano','social lounge','SURA GRAND Piano.step'),
 ('table-tennis','Table Tennis','social lounge','table tennis.igs'),
 ('foosball-native','Table Football - Native','social lounge','Tablefootball.SLDPRT'),
 ('bathtub','Bathtub','bathroom stuff + locker stuff','bathtub.STEP'),
 ('vanity','Bathroom Vanity','bathroom stuff + locker stuff','MASTER BATHROOM - VANITY-00.stp'),
 ('showerhead','Showerhead','bathroom stuff + locker stuff','Showerhead.SLDPRT'),
 ('locker','Staff Locker','bathroom stuff + locker stuff','STAFF LOCKER.STEP'),
 ('toilet','Toilet','bathroom stuff + locker stuff','Toilet seat.stp'),
]
REVIEW={key:dict(rotation=[-90,0,0] if key in {
    'unknown-seat','drawer','massage-chair','chess-set','chess-pieces','sideboard','sofa',
    'piano','table-tennis','vanity','toilet'} else [0,0,0]) for key,*_ in ITEMS}
REVIEW['unknown-seat'].update(name='Two-Seat Upholstered Bench',note='Identified visually as a two-seat bench; provisional STL scale.')
REVIEW['folding-pingpong'].update(name='Table Tennis Table with Net',note='Open playing configuration; native Y-up verified visually.')
REVIEW['piano'].update(name='Miniature Piano - Scale Review Required',note='Source is 287 mm wide; not selected for the room furnishing.')
REVIEW['foosball'].update(name='Tabletop Foosball Game',note='Source is a 410 x 502 mm tabletop game, not a full-size floor-standing table.')
REVIEW['locker'].update(name='Six-Compartment Staff Locker',note='Includes open cabinet doors; full open-door envelope retained.')
REVIEW['massage-chair'].update(note='Concept-size display copy enlarged 20x to approximately 1.82 m long; original CAD retained. Manufacturer dimensions require confirmation.')
REVIEW['arcade'].update(note='Concept-size display copy enlarged 18x to approximately 1.97 m high; original CAD retained. Manufacturer dimensions require confirmation.')


def normalize():
    # Preserve the imported source and make explicit, reversible concept-scale copies.
    for key,*_ in ITEMS:
        scale={'massage-chair':20,'arcade':18}.get(key,1)
        folder=base.LIBRARY/('gym-wellness-'+key)
        receipt=json.loads((OUT/('asset-gym-wellness-'+key+'-conversion.json')).read_text())
        source=ROOT/receipt['artifact']
        raw=source.read_bytes()
        n=struct.unpack_from('<I',raw,12)[0]
        doc=json.loads(raw[20:20+n]);binary=raw[28+n:]
        omitted=[]
        for i,mesh in enumerate(doc['meshes']):
            kept=[]
            for p in mesh['primitives']:
                if p.get('mode',4)==4:kept.append(p)
                else:omitted.append(dict(mesh=i,name=mesh.get('name'),mode=p.get('mode')))
            mesh['primitives']=kept
            if not kept:
                for node in doc['nodes']:
                    if node.get('mesh')==i:node.pop('mesh')
        if scale==1 and not omitted:continue
        if scale!=1:
            for scene in doc['scenes']:
                root=len(doc['nodes'])
                doc['nodes'].append(dict(name='Provisional concept scale',scale=[scale]*3,children=scene['nodes']))
                scene['nodes']=[root]
        encoded=json.dumps(doc,separators=(',',':')).encode();encoded+=b' '*(-len(encoded)%4)
        payload=(struct.pack('<4sII',b'glTF',2,28+len(encoded)+len(binary))+
            struct.pack('<I4s',len(encoded),b'JSON')+encoded+struct.pack('<I4s',len(binary),b'BIN\0')+binary)
        (folder/'model-display.glb').write_bytes(payload)
        base.write(folder/'concept-scale.json',dict(sourceSha256=base.sha(source),
            displaySha256=base.sha(folder/'model-display.glb'),uniformFactor=scale,
            omittedNonSurfacePrimitives=omitted,authority='provisional_concept_size' if scale!=1 else 'source_CAD',
            requiresManufacturerConfirmation=scale!=1))
    base.write(OUT/'orientation-review.json',{'asset-gym-wellness-'+k:v for k,v in REVIEW.items()})


def convert():
    import numpy as np
    import trimesh
    OUT.mkdir(parents=True,exist_ok=True)
    inventory=[]
    for key,name,folder,filename in ITEMS:
        source=SOURCE/folder/filename
        target=base.LIBRARY/('gym-wellness-'+key);target.mkdir(parents=True,exist_ok=True)
        if not (target/filename).exists():shutil.copy2(source,target/filename)
        assert base.sha(source)==base.sha(target/filename)
        item=dict(assetId='asset-gym-wellness-'+key,displayName=name,source=filename,
                  sourceSha256=base.sha(source),format=source.suffix.lower(),target=target.relative_to(ROOT).as_posix())
        inventory.append(item)
        receipt=OUT/(item['assetId']+'-conversion.json')
        if receipt.exists() and json.loads(receipt.read_text()).get('status')=='converted':continue
        print('Converting '+name,flush=True)
        try:
            if item['format']=='.stl':
                mesh=trimesh.load_mesh(target/filename,process=False)
                bounds=mesh.bounds.copy()
                assert np.isfinite(mesh.vertices).all() and len(mesh.faces)>0
                scale=.001 if key.startswith('chess') else .01
                mesh.apply_scale(scale)
                (target/'model.glb').write_bytes(trimesh.Scene(mesh).export(file_type='glb'))
                result=dict(artifact=(target/'model.glb').relative_to(ROOT).as_posix(),sourceBounds=bounds.tolist(),
                    sourceTriangles=len(mesh.faces),units=dict(sourceUnits='unspecified',
                    assumedUnits='mm' if scale==.001 else 'cm',scaleToMeters=scale,
                    authority='provisional_human_scale_interpretation',requiresConfirmation=True))
            elif item['format']=='.sldprt':
                exporter=ROOT/'.runtime/additional-gym-import-20261004/bin/AdditionalGymPartExporter.exe'
                with (target/'extractor.log').open('w') as log:
                    proc=subprocess.run([str(exporter),str(target/filename),str(target)],stdout=log,
                        stderr=subprocess.STDOUT,timeout=300,creationflags=subprocess.CREATE_NO_WINDOW)
                assert proc.returncode==0,(target/'extractor.log').read_text()
                evidence=json.loads((target/'native-export.json').read_text(encoding='utf-8-sig'))
                bodies=json.loads((target/'model_process_bodies.json').read_text(encoding='utf-8-sig'))['bodies']
                assert len(bodies)==evidence['visibleBodies']
                assert sum(b['faceCount'] for b in bodies)==evidence['visibleFaces']
                result=dict(artifact=(target/'model_body.glb').relative_to(ROOT).as_posix(),nativeEvidence=evidence,
                            units=dict(sourceUnits='m',authority='SolidWorks_API_meters'))
            else:
                result=base.convert_interchange(item,retry_failed_faces=True)
                result['emptyCompoundNodesRemoved']=remove_empty_cad_nodes(ROOT/result['artifact'])
            result.update(status='converted',assetId=item['assetId'],sourceSha256=item['sourceSha256'])
        except Exception as exc:
            traceback.print_exc()
            result=dict(status='failed',assetId=item['assetId'],error=str(exc))
        base.write(receipt,result)
        print(json.dumps(result),flush=True)
    base.write(OUT/'inventory.json',inventory)


def measure():
    import trimesh
    result=[]
    for path in sorted(OUT.glob('*-conversion.json')):
        item=json.loads(path.read_text())
        if item['status']!='converted':continue
        scene=trimesh.load_scene(ROOT/item['artifact'],process=False)
        result.append(dict(assetId=item['assetId'],artifact=item['artifact'],bounds=scene.bounds.tolist(),
            dimensions=scene.extents.tolist(),meshes=len(scene.geometry),
            names=list(scene.geometry)[:50]))
    base.write(OUT/'measurements.json',result)
    print(json.dumps(result))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','prepare','measure','normalize'])
    parser.add_argument('--review',type=Path)
    args=parser.parse_args()
    if args.phase=='convert':convert()
    elif args.phase=='normalize':normalize()
    elif args.phase=='measure':measure()
    else:
        base.OUT=OUT
        base.prepare(args.review,set())
        for item in json.loads((OUT/'inventory.json').read_text()):
            path=ROOT/item['target']/'catalog-entry.json'
            if not path.exists():continue
            entry=json.loads(path.read_text())
            units=entry['source'].get('unitInterpretation',{})
            if units.get('requiresConfirmation'):
                entry['description']=entry['description'].replace('interpreted as centimetres',
                    'interpreted as '+('millimetres' if units['assumedUnits']=='mm' else 'centimetres'))
            scale_path=ROOT/item['target']/'concept-scale.json'
            if scale_path.exists():entry['source']['conceptScale']=json.loads(scale_path.read_text())
            base.write(path,entry)
