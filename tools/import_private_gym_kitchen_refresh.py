"""Inspect supplied espresso machine and grill before publishing replacements."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT=ROOT/'.runtime/private-gym-kitchen-refresh-20261011'
SOURCE=Path('C:/Users/might/Downloads/Decorative object')
ITEMS=[('espresso','Espresso Machine','expresso machine.STEP'),('grill','Patio Grill','Grill.STEP')]


def inventory():
    OUT.mkdir(parents=True,exist_ok=True)
    items=[]
    for key,name,filename in ITEMS:
        target=base.LIBRARY/('gym-kitchen-refresh-'+key);target.mkdir(parents=True,exist_ok=True)
        if not (target/filename).exists():copy2(SOURCE/filename,target/filename)
        digest=base.sha(SOURCE/filename);assert base.sha(target/filename)==digest
        items.append(dict(assetId='asset-gym-kitchen-refresh-'+key,displayName=name,source=filename,
            sourceSha256=digest,format='step',target=target.relative_to(ROOT).as_posix()))
    base.write(OUT/'inventory.json',items)
    return items


def convert():
    for item in inventory():
        key=item['assetId'].removeprefix('asset-gym-kitchen-refresh-')
        receipt=OUT/(key+'-conversion.json')
        if receipt.exists():
            previous=json.loads(receipt.read_bytes());assert previous['sourceSha256']==item['sourceSha256']
            if previous['status']=='converted':continue
        print('Converting '+item['displayName'],flush=True)
        result=base.convert_interchange(item,True,negligible_face_area_mm2=.000001)
        result['emptyCompoundNodesRemoved']=remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted',sourceSha256=item['sourceSha256'])
        base.write(receipt,result);print(json.dumps(result),flush=True)


def inspect():
    from tools.apex_equipment_materials import np,trimesh
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    for item in inventory():
        key=item['assetId'].removeprefix('asset-gym-kitchen-refresh-');target=ROOT/item['target']
        scene=trimesh.load_scene(target/'model.glb',process=False);records=[]
        for node in scene.graph.nodes_geometry:
            transform,name=scene.graph[node];mesh=scene.geometry[name]
            points=trimesh.transform_points(mesh.vertices,transform)
            records.append(dict(node=node,name=name,triangles=len(mesh.faces),bounds=[points.min(axis=0).tolist(),points.max(axis=0).tolist()]))
        b=np.array([r['bounds'] for r in records]);lo,hi=b[:,0].min(axis=0),b[:,1].max(axis=0)
        result=dict(assetId=item['assetId'],bounds=[lo.tolist(),hi.tolist()],dimensions=(hi-lo).tolist(),
            triangles=sum(r['triangles'] for r in records),components=records)
        base.write(OUT/(key+'-geometry.json'),result)
        render_software_thumbnail(target/'model.glb',OUT/(key+'-source.webp'),maximum_triangles=700000)
        print(json.dumps({k:v for k,v in result.items() if k!='components'}),flush=True)


def grill_components():
    from tools.apex_equipment_materials import np,trimesh
    path=base.LIBRARY/'gym-kitchen-refresh-grill/model.glb'
    mesh=trimesh.load_scene(path,process=False).to_geometry();mesh.merge_vertices()
    groups=trimesh.graph.connected_components(mesh.face_adjacency,nodes=np.arange(len(mesh.faces)),min_len=1)
    result=[]
    for faces in groups:
        points=mesh.vertices[mesh.faces[faces]].reshape(-1,3)
        result.append(dict(faces=len(faces),bounds=[points.min(axis=0).tolist(),points.max(axis=0).tolist()]))
    base.write(OUT/'grill-connected-components.json',result)
    print(json.dumps(sorted(result,key=lambda c:c['faces'],reverse=True)[:80]),flush=True)


def prepare():
    from functools import partial
    from tools.apex_equipment_materials import np,trimesh,material,unpack,pack
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    import publish_local_machine_library as publisher
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES=0
    publisher.render_software_thumbnail=partial(render_software_thumbnail,maximum_triangles=1200000)
    for item in inventory():
        key=item['assetId'].removeprefix('asset-gym-kitchen-refresh-');target=ROOT/item['target']
        conversion=json.loads((OUT/(key+'-conversion.json')).read_bytes())
        assert conversion['status']=='converted' and conversion['sourceFaces']==conversion['meshedFaces']
        scene=trimesh.load_scene(target/'model.glb',process=False);parts=[];records=[]
        for node in scene.graph.nodes_geometry:
            matrix,name=scene.graph[node];mesh=scene.geometry[name].copy();mesh.apply_transform(matrix)
            if key=='grill':
                mesh.merge_vertices();groups=trimesh.graph.connected_components(mesh.face_adjacency,nodes=np.arange(len(mesh.faces)),min_len=1)
                for faces in groups:
                    part=mesh.submesh([faces],append=True,repair=False);lo,hi=part.bounds
                    role='frame'
                    # Whole connected handles, controls and grates identified from their CAD bounds.
                    if ((lo[1]>1.50 and lo[2]>.05) or (.58<lo[1]<.60 and hi[1]<.64 and lo[2]>.31)
                        or (lo[2]>.409 and .76<lo[1]<.79 and hi[1]<.84)
                        or len(faces) in (21008,16024,24008)):
                        role='gold'
                    parts.append((part,role));records.append(dict(name='connected-'+str(len(records)),sourceTriangles=len(faces),displayTriangles=len(faces),role=role,bounds=part.bounds.tolist(),maxBoundsChangeMeters=0))
                continue
            source_bounds=mesh.bounds.copy();count=len(mesh.faces);reduced=mesh
            if count>10000:
                welded=mesh.copy();welded.merge_vertices()
                for fraction in (.04,.08,.15,.30,.50):
                    test=welded.simplify_quadric_decimation(face_count=max(800,int(count*fraction)),aggression=4)
                    if np.max(np.abs(test.bounds-source_bounds))<=.0005:
                        reduced=test;break
            role='gold'
            if name in ('10000136','10000075','10000125','frame front','Frame Bottom') or name.lower().startswith('frame'):role='vehicle_paint'
            if name=='300200' or name.startswith('40000070') or source_bounds[1,1]<.011:role='rubber'
            if name=='water':role='water'
            parts.append((reduced,role));records.append(dict(name=name,sourceTriangles=count,displayTriangles=len(reduced.faces),role=role,bounds=source_bounds.tolist(),maxBoundsChangeMeters=float(np.max(np.abs(reduced.bounds-source_bounds)))))
        bounds=np.array([m.bounds for m,_ in parts]);lo,hi=bounds[:,0].min(axis=0),bounds[:,1].max(axis=0)
        offset=[-(lo[0]+hi[0])/2,-lo[1],-(lo[2]+hi[2])/2];groups={}
        for mesh,role in parts:
            mesh.apply_translation(offset);groups.setdefault(role,[]).append(mesh)
        display=trimesh.Scene()
        for role,meshes in groups.items():
            mesh=trimesh.util.concatenate(meshes)
            mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
            display.add_geometry(mesh,node_name=role,geom_name=role)
        doc,data=unpack(display.export(file_type='glb',include_normals=True))
        for i,m in enumerate(doc['materials']):
            role=m['name'].removeprefix('APEX ')
            if role=='water':
                doc['materials'][i]=dict(name='Retained water geometry',pbrMetallicRoughness=dict(baseColorFactor=[.7,.85,1,.12],metallicFactor=0,roughnessFactor=.2),alphaMode='BLEND',doubleSided=True,extras=dict(facilityAuthoredFinish=True))
            else:doc['materials'][i]=material(role)
        artifact=target/'model-display.glb';artifact.write_bytes(pack(doc,data))
        description='User-supplied STEP CAD at native unit-converted scale. APEX black-and-gold finish. Original full-resolution CAD retained; installation, operating clearances and utility requirements unverified.'
        source=publisher.SourceAsset(item['assetId'],'APEX '+item['displayName'],'Building Elements',item['source'],'interchange',description,('kitchen' if key=='espresso' else 'patio','APEX','black and gold',key),(0,0,0))
        entry=publisher._catalog_entry(source,target/item['source'],artifact,target)
        entry['source'].update(format='step',unitInterpretation=conversion['units'])
        entry['visualImport']=dict(sourceSha256=base.sha(target/'model.glb'),displaySha256=base.sha(artifact),
            sourceTriangles=sum(r['sourceTriangles'] for r in records),displayTriangles=sum(r['displayTriangles'] for r in records),
            maxPartBoundsChangeMeters=max(r['maxBoundsChangeMeters'] for r in records),nativeScalePreserved=True,
            canonicalFront='+Z',sourceFaces=conversion['sourceFaces'],meshedFaces=conversion['meshedFaces'],parts=records)
        base.write(target/'catalog-entry.json',entry)
        print(json.dumps(dict(assetId=item['assetId'],dimensions=entry['dimensions'],triangles=entry['visualImport']['displayTriangles'])),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('phase',choices=['convert','inspect','grill-components','prepare'])
    {'convert':convert,'inspect':inspect,'grill-components':grill_components,'prepare':prepare}[parser.parse_args().phase]()
