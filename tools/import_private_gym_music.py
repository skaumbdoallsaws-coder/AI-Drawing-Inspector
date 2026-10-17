"""Inspect supplied entertainment-room CAD without publishing unreviewed assets."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT=ROOT/'.runtime/private-gym-music-20261011'
SOURCE=Path('C:/Users/might/Downloads/Decorative object')
ITEMS=[('piano','Piano Assembly','piano_assesmbly_asm.stp'),
       ('steinway','Steinway Piano Assembly','STIENWAY PIANO ENSAMBLE.STEP'),
       ('electric-guitar','Electric Guitar','E-guitar.stp'),
       ('guitar','Guitar','guitare.stp'),
       ('egg-chair','Egg Chair','Egg_Chair.igs'),
       ('gramophone','Gramophone','Gramophone.stp')]


def inventory():
    OUT.mkdir(parents=True,exist_ok=True)
    items=[]
    for key,name,filename in ITEMS:
        target=base.LIBRARY/('gym-music-'+key)
        target.mkdir(parents=True,exist_ok=True)
        if not (target/filename).exists():copy2(SOURCE/filename,target/filename)
        digest=base.sha(SOURCE/filename)
        assert base.sha(target/filename)==digest
        items.append(dict(assetId='asset-gym-music-'+key,displayName=name,source=filename,
            sourceSha256=digest,format=Path(filename).suffix.lower(),target=target.relative_to(ROOT).as_posix()))
    base.write(OUT/'inventory.json',items)
    return items


def convert(keys):
    for item in inventory():
        key=item['assetId'].removeprefix('asset-gym-music-')
        if keys and key not in keys:continue
        receipt=OUT/(key+'-conversion.json')
        if receipt.exists():
            previous=json.loads(receipt.read_bytes())
            assert previous['sourceSha256']==item['sourceSha256']
            if previous['status']=='converted':continue
        print('Converting '+item['displayName'],flush=True)
        start=time.monotonic()
        try:
            limit=.000001
            if key=='egg-chair':
                assert item['sourceSha256']=='97f04de119ec18e1ec088ae4e7a2173a4b1ae6ebe1e7e47d66692495a5d681a5'
                limit=.0005
            result=base.convert_interchange(item,True,negligible_face_area_mm2=limit)
            if key=='egg-chair':
                assert result['sourceFaces']==1387 and result['meshedFaces']==1382
                assert len(result['negligibleFaces'])==5
                assert sum(f['areaSquareMillimeters'] for f in result['negligibleFaces'])<.0005
            result['emptyCompoundNodesRemoved']=remove_empty_cad_nodes(ROOT/result['artifact'])
            result['status']='converted'
        except Exception as exc:
            result=dict(status='failed',error=str(exc))
        result.update(assetId=item['assetId'],sourceSha256=item['sourceSha256'],seconds=round(time.monotonic()-start,2))
        base.write(receipt,result)
        print(json.dumps(result),flush=True)


def inspect(keys):
    from tools.apex_equipment_materials import np,trimesh
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    for item in inventory():
        key=item['assetId'].removeprefix('asset-gym-music-')
        if keys and key not in keys:continue
        conversion=json.loads((OUT/(key+'-conversion.json')).read_bytes())
        if conversion['status']!='converted':continue
        target=ROOT/item['target']
        scene=trimesh.load_scene(target/'model.glb',process=False)
        records=[]
        for node in scene.graph.nodes_geometry:
            transform,name=scene.graph[node]
            mesh=scene.geometry[name]
            points=trimesh.transform_points(mesh.vertices,transform)
            records.append(dict(node=node,name=name,triangles=len(mesh.faces),bounds=[points.min(axis=0).tolist(),points.max(axis=0).tolist()]))
        b=np.array([r['bounds'] for r in records])
        lo,hi=b[:,0].min(axis=0),b[:,1].max(axis=0)
        result=dict(assetId=item['assetId'],bounds=[lo.tolist(),hi.tolist()],dimensions=(hi-lo).tolist(),
                    triangles=sum(r['triangles'] for r in records),components=records)
        base.write(OUT/(key+'-geometry.json'),result)
        render_software_thumbnail(target/'model.glb',OUT/(key+'-source.webp'),maximum_triangles=600000)
        print(json.dumps({k:v for k,v in result.items() if k!='components'}),flush=True)


def prepare(keys):
    from functools import partial
    from tools.apex_equipment_materials import np,trimesh,material,unpack,pack
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    import publish_local_machine_library as publisher
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES=0
    publisher.render_software_thumbnail=partial(render_software_thumbnail,maximum_triangles=700000)
    for item in inventory():
        key=item['assetId'].removeprefix('asset-gym-music-')
        if key not in {'steinway','electric-guitar','egg-chair'} or (keys and key not in keys):continue
        target=ROOT/item['target']
        conversion=json.loads((OUT/(key+'-conversion.json')).read_bytes())
        assert conversion['status']=='converted'
        scene=trimesh.load_scene(target/'model.glb',process=False)
        rotation=np.eye(4)
        if key=='egg-chair':rotation[:3,:3]=[[1,0,0],[0,0,1],[0,-1,0]]
        if key=='electric-guitar':rotation[:3,:3]=[[0,0,-1],[1,0,0],[0,-1,0]]
        records=[];parts=[]
        for node in scene.graph.nodes_geometry:
            transform,name=scene.graph[node]
            mesh=scene.geometry[name].copy()
            mesh.apply_transform(rotation@transform)
            bounds=mesh.bounds.copy();count=len(mesh.faces)
            reduced=mesh
            if key=='electric-guitar' and count>2500 and 'struna' not in name.lower():
                merged=mesh.copy();merged.merge_vertices()
                for fraction in (.15,.30,.50):
                    candidate=merged.simplify_quadric_decimation(face_count=max(800,int(count*fraction)),aggression=4)
                    if np.max(np.abs(candidate.bounds-bounds))<=.001:
                        reduced=candidate;break
            if key=='steinway':
                role={'Piano_Open':'gold','Piano_Open_1':'vehicle_paint','Piano_Open_2':'gold',
                      'Piano_Open_3':'rubber','Piano_Open_4':'ivory','Piano Bench':'vehicle_paint',
                      'Piano Bench_1':'gold'}[name]
            elif key=='egg-chair':
                role='gold' if name=='Door' or name.startswith('GLTF') else 'rubber' if name=='iphone 4' else 'frame'
            else:
                role='vehicle_paint' if name=='korpus-oa1' else 'frame' if name.startswith(('Gryf','podstrunnica','zwartblokje')) else 'gold'
            records.append(dict(name=name,node=node,sourceTriangles=count,displayTriangles=len(reduced.faces),
                                role=role,maximumBoundsChangeMeters=float(np.max(np.abs(reduced.bounds-bounds)))))
            parts.append((reduced,role,name))
        all_bounds=np.array([m.bounds for m,r,n in parts])
        lo,hi=all_bounds[:,0].min(axis=0),all_bounds[:,1].max(axis=0)
        offset=np.array([-(lo[0]+hi[0])/2,-lo[1],-(lo[2]+hi[2])/2])
        for mesh,role,name in parts:mesh.apply_translation(offset)
        authored=0
        if key=='electric-guitar':
            rear=-(hi[2]-lo[2])/2
            for name,size,center,role in [
                ('Hanger wall plate',[.07,.10,.008],[0,.745,rear-.036],'frame'),
                ('Hanger arm',[.025,.025,.08],[0,.722,rear+.008],'gold'),
                ('Hanger left prong',[.012,.035,.045],[-.027,.735,.005],'rubber'),
                ('Hanger right prong',[.012,.035,.045],[.027,.735,.005],'rubber')]:
                mesh=trimesh.creation.box(size);mesh.apply_translation(center)
                parts.append((mesh,role,name));authored+=len(mesh.faces)
            b=np.array([m.bounds for m,r,n in parts]);minimum=b[:,0].min(axis=0);maximum=b[:,1].max(axis=0)
            for mesh,role,name in parts:mesh.apply_translation([-(minimum[0]+maximum[0])/2,0,-(minimum[2]+maximum[2])/2])
        variants=['black','gold'] if key=='electric-guitar' else ['black']
        for variant in variants:
            groups={}
            for mesh,role,name in parts:
                if key=='electric-guitar' and name=='korpus-oa1' and variant=='gold':role='gold'
                groups.setdefault(role,[]).append(mesh)
            display=trimesh.Scene()
            for role,meshes in groups.items():
                mesh=trimesh.util.concatenate(meshes)
                mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
                display.add_geometry(mesh,node_name=role,geom_name=role)
            doc,data=unpack(display.export(file_type='glb',include_normals=True))
            for i,m in enumerate(doc['materials']):
                role=m['name'].removeprefix('APEX ')
                if role=='ivory':
                    doc['materials'][i]=dict(name='Piano natural keys',pbrMetallicRoughness=dict(
                        baseColorFactor=[.92,.92,.87,1],metallicFactor=0,roughnessFactor=.4),
                        doubleSided=True,extras=dict(facilityAuthoredFinish=True))
                else:doc['materials'][i]=material(role)
            name='model-display-gold.glb' if variant=='gold' else 'model-display.glb'
            artifact=target/name;artifact.write_bytes(pack(doc,data))
            aid=item['assetId']+('-gold' if variant=='gold' else '')
            title={'steinway':'APEX Upright Piano and Bench','electric-guitar':'APEX Wall Guitar - '+variant.title(),
                   'egg-chair':'APEX Egg Chair'}[key]
            description='User-supplied CAD at native unit-converted scale. Black-and-gold finish; original source and full-resolution GLB retained.'
            if key=='electric-guitar':description+=' Authored concept neck hanger. Geometry alignment does not qualify anchors or mounting loads.'
            if key=='egg-chair':description+=' Source includes an open side panel and integrated accessories. Five source slivers totaling less than 0.0005 square millimeters are omitted.'
            source=publisher.SourceAsset(aid,title,'Office & IT',item['source'],'interchange',description,
                ('gym','music','lounge','APEX','black and gold'),(0,0,0))
            entry=publisher._catalog_entry(source,target/item['source'],artifact,target)
            entry['source'].update(format=item['format'].lstrip('.'),unitInterpretation=conversion['units'])
            entry['visualImport']=dict(sourceSha256=base.sha(target/'model.glb'),displaySha256=base.sha(artifact),
                sourceTriangles=sum(r['sourceTriangles'] for r in records),displayTriangles=sum(r['displayTriangles'] for r in records)+authored,
                sourceComponents=len(records),displayComponentsRetained=len(records),authoredHangerTriangles=authored,
                maximumPartBoundsChangeMeters=max(r['maximumBoundsChangeMeters'] for r in records),
                sourceToDisplayUniformScale=1,sourceRotationMatrix=rotation.tolist(),canonicalFront='+Z',parts=records,
                sourceFaces=conversion['sourceFaces'],meshedFaces=conversion['meshedFaces'],negligibleFaces=conversion['negligibleFaces'])
            base.write(target/('catalog-entry-gold.json' if variant=='gold' else 'catalog-entry.json'),entry)
            print(json.dumps(dict(assetId=aid,dimensions=entry['dimensions'],triangles=entry['visualImport']['displayTriangles'])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','inspect','prepare'])
    parser.add_argument('--key',action='append',default=[])
    args=parser.parse_args()
    {'convert':convert,'inspect':inspect,'prepare':prepare}[args.phase](set(args.key))
