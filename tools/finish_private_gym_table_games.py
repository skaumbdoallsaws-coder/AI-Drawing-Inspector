"""Non-destructive APEX display finishes for the supplied table-game models."""
from functools import partial
import hashlib
import json
from pathlib import Path
import re
from shutil import copy2
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'tools')]
from tools.import_private_gym_table_games import OUT, A, inventory, base
from tools.apex_equipment_materials import np, trimesh, material, unpack, pack
from tools.gym_theme_wall import linear_rgb
from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
from PIL import Image
import publish_local_machine_library as publisher

COLORS = ['#F1BB19','#165DAA','#C52432','#63398C','#EF6B25','#217846','#822537',
          '#121416','#F1BB19','#165DAA','#C52432','#63398C','#EF6B25','#217846','#822537']


def paint(role):
    if role.startswith('ball-'):
        color = COLORS[int(role.split('-')[1])%len(COLORS)]
        metal,rough = 0,.24
    elif role == 'ivory':
        color,metal,rough = '#EEEAD9',0,.35
    elif role == 'felt':
        color,metal,rough = '#145A35',0,.92
    else:
        return material(role)
    return dict(name='APEX '+role,doubleSided=True,extras=dict(facilityAuthoredFinish=True),
        pbrMetallicRoughness=dict(baseColorFactor=linear_rgb(color)+[1],metallicFactor=metal,roughnessFactor=rough))


def export(parts, artifact):
    scene = trimesh.Scene()
    groups = {}
    for mesh,role in parts:
        groups.setdefault(role,[]).append(mesh)
    for role,meshes in groups.items():
        merged = trimesh.util.concatenate(meshes)
        merged.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
        scene.add_geometry(merged,node_name=role,geom_name=role)
    doc,data = unpack(scene.export(file_type='glb',include_normals=True))
    for i,mat in enumerate(doc['materials']):
        doc['materials'][i] = paint(mat['name'].removeprefix('APEX '))
    artifact.write_bytes(pack(doc,data))


def prepare():
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES = 0
    publisher.render_software_thumbnail = partial(render_software_thumbnail,maximum_triangles=100000)
    for item in inventory():
        key = item['assetId'].removeprefix(A)
        target = ROOT/item['target']
        if (target/'catalog-entry.json').exists():
            print('Already prepared '+key,flush=True)
            continue
        if key!='balls' and not (OUT/(key+'-conversion.json')).exists():
            continue
        records,parts,points = [],[],[]
        reduced_cache = {}
        rotation = np.eye(4)
        if key=='foosball':
            rotation[:3,:3] = [[1,0,0],[0,0,1],[0,-1,0]]
        if key=='balls':
            mesh = trimesh.load_mesh(target/item['source'],process=True)
            components = mesh.split(only_watertight=False)
            assert len(components)==15 and all(m.is_watertight for m in components)
            assert all(np.allclose(m.extents,5.715,atol=.003) for m in components)
            center = mesh.bounds.mean(axis=0)
            for i,m in enumerate(components):
                c = m.bounds.mean(axis=0)
                m.apply_translation(-c)
                m.apply_scale(.01)
                m.apply_translation([(c[0]-center[0])*.028,m.extents[1]/2,(c[2]-center[2])*.018])
                ids = np.arange(len(m.faces))
                white = np.abs(m.triangles_center[:,1]-m.bounds.mean(axis=0)[1])>.014 if i>=8 else np.zeros(len(ids),dtype=bool)
                for mask,role in [(~white,'ball-'+str(i)),(white,'ivory')]:
                    if mask.any():
                        parts.append((m.submesh([ids[mask]],append=True,repair=False),role))
                records.append(dict(component=i,sourceFaces=len(m.faces),role='ball-'+str(i),
                    diameterMeters=m.extents.tolist(),bounds=m.bounds.tolist()))
            conversion = dict(units=dict(sourceUnits='unspecified',assumedUnits='cm',scaleToMeters=.01,
                authority='inferred_from_5.715_source_unit_spheres',requiresConfirmation=True),
                sourceTriangles=len(mesh.faces),meshedTriangles=sum(len(m.faces) for m in components))
        else:
            conversion = json.loads((OUT/(key+'-conversion.json')).read_bytes())
            scene = trimesh.load_scene(target/'model.glb',process=False)
            for node in scene.graph.nodes_geometry:
                matrix,name = scene.graph[node]
                source = scene.geometry[name]
                if not isinstance(source,trimesh.Trimesh):
                    assert len(source.vertices)==1
                    points.append(name)
                    continue
                m = source.copy()
                reduction = None
                if key=='organizer' and len(m.faces)>12000:
                    digest=hashlib.sha256(m.vertices.tobytes()+m.faces.tobytes()).hexdigest()
                    if digest not in reduced_cache:
                        welded=m.copy();welded.merge_vertices()
                        reduced=m
                        for fraction in (.08,.16,.3,.5):
                            candidate=welded.simplify_quadric_decimation(face_count=max(600,int(len(m.faces)*fraction)),aggression=4)
                            if np.max(np.abs(candidate.bounds-m.bounds))<=.001 and abs(candidate.area-m.area)/max(m.area,1e-12)<=.025:
                                reduced=candidate
                                break
                        reduced_cache[digest]=reduced
                    reduced=reduced_cache[digest]
                    reduction=dict(sourceTriangles=len(m.faces),displayTriangles=len(reduced.faces),
                        boundsDeltaMeters=float(np.max(np.abs(reduced.bounds-m.bounds))),
                        relativeAreaDelta=float(abs(reduced.area-m.area)/max(m.area,1e-12)))
                    m=reduced.copy()
                m.apply_transform(rotation@matrix)
                role = 'frame'
                n = re.sub(r'_\d+$','',name)
                if key=='foosball':
                    if n.startswith(('Sipka','Vijak','Zavrtanj','ISO','Podloska')):
                        role='steel'
                    elif n.startswith(('Guma','Zastitna','SOLID','COMPOUND')):
                        role='rubber'
                    elif n in ('Noga stola','Nosac','Limovi','Pepeljara'):
                        role='gold'
                    elif n=='Teren':
                        role='felt'
                    elif n.startswith(('Loptica','Rezervne')):
                        role='ivory'
                    elif n=='Igrac':
                        x=float(m.bounds.mean(axis=0)[0])
                        role='gold' if any(abs(x-p)<.01 for p in (-.525,-.375,-.075,.225)) else 'ivory'
                elif key=='blackjack':
                    centers=m.triangles_center
                    tabletop=(np.abs(centers[:,1])<1e-6)&(m.face_normals[:,1]>.999)
                    rim=centers[:,1]>.0001
                    for mask,r in [(tabletop,'tabletop'),(~tabletop&rim,'gold'),(~tabletop&~rim,'frame')]:
                        if mask.any():
                            parts.append((m.submesh([np.flatnonzero(mask)],append=True,repair=False),r))
                    records.append(dict(name=name,sourceTriangles=len(m.faces),tabletopFaces=int(tabletop.sum()),rimFaces=int(rim.sum())))
                    continue
                elif key=='organizer':
                    if n.startswith('BALL '):role='ball-'+str(int(n.split()[1])-1)
                    elif n=='CUE BALL 1':role='ivory'
                    elif n in ('Cabinet Handle','cue bridge','CUE HOLDER RACK','pool ball rack','CUE HOLDER BOTTOM'):
                        role='gold'
                    elif n.startswith('thumb screw'):role='steel'
                    elif n=='Pool Chalk':role='ball-1'
                    elif n=='CUE STICK':
                        ids=np.arange(len(m.faces));gold=m.triangles_center[:,1]>.95
                        for mask,r in [(gold,'gold'),(~gold,'frame')]:
                            if mask.any():parts.append((m.submesh([ids[mask]],append=True,repair=False),r))
                        records.append(dict(name=name,role='gold-shaft-black-grip',sourceTriangles=len(source.faces),reduction=reduction))
                        continue
                parts.append((m,role))
                records.append(dict(name=name,role=role,sourceTriangles=len(source.faces),displayTriangles=len(m.faces),reduction=reduction))
        bounds=np.array([m.bounds for m,_ in parts])
        lo,hi=bounds[:,0].min(axis=0),bounds[:,1].max(axis=0)
        offset=np.array([-(lo[0]+hi[0])/2,-lo[1],-(lo[2]+hi[2])/2])
        for m,_ in parts:
            m.apply_translation(offset)
        artifact=target/'model-display.glb'
        if key=='blackjack':
            copy2(Path('C:/Users/might/Downloads/Decorative object/blackjack.png'),target/'blackjack.png')
            scene=trimesh.Scene()
            image=Image.open(target/'blackjack.png').convert('RGBA')
            for m,role in parts:
                if role=='tabletop':
                    # Uniform planar image scale; the curved CAD face clips the image at its boundary.
                    b=m.bounds;w=b[1,0]-b[0,0];h=w*image.height/image.width
                    cx=(b[0,0]+b[1,0])/2;cz=(b[0,2]+b[1,2])/2
                    uv=np.column_stack(((m.vertices[:,0]-cx)/w+.5,.5-(m.vertices[:,2]-cz)/h))
                    m.visual=trimesh.visual.TextureVisuals(uv=uv,material=trimesh.visual.material.PBRMaterial(
                        name='Supplied blackjack cloth',baseColorFactor=[255,255,255,255],baseColorTexture=image,
                        metallicFactor=0,roughnessFactor=.85,doubleSided=True))
                else:
                    m.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
                scene.add_geometry(m,node_name=role,geom_name=role)
            doc,data=unpack(scene.export(file_type='glb',include_normals=True))
            for i,mat in enumerate(doc['materials']):
                if mat['name'].startswith('APEX '):doc['materials'][i]=paint(mat['name'][5:])
                else:mat['extras']=dict(facilityAuthoredFinish=True)
            artifact.write_bytes(pack(doc,data))
        else:
            export(parts,artifact)
        description='User-supplied table-game geometry with an APEX display finish. Original source retained.'
        if key=='balls':description+=' STL units inferred as centimetres; ball positions spread for display, individual geometry unchanged.'
        source=publisher.SourceAsset(A+key,'APEX '+item['displayName'],'Office & IT',item['source'],
            'part' if key=='blackjack' else 'interchange',description,('gym','games','APEX',key),(0,0,0))
        entry=publisher._catalog_entry(source,target/item['source'],artifact,target)
        entry['source'].update(format=item['format'].lstrip('.'),unitInterpretation=conversion['units'])
        entry['dimensions']=dict(zip(('width','height','depth'),(hi-lo).tolist()))
        entry['sourceToCanonical']=np.eye(4).flatten(order='F').tolist()
        entry['visualImport']=dict(displaySha256=base.sha(artifact),sourceRotationMatrix=rotation.tolist(),
            sourceOffset=offset.tolist(),parts=records,omittedNonSurfaceReferencePoints=points,
            triangles=sum(len(m.faces) for m,_ in parts),allComponentsRetained=True,
            allSurfaceTrianglesRetained=key!='organizer',
            textureSha256=base.sha(target/'blackjack.png') if key=='blackjack' else None)
        base.write(target/'catalog-entry.json',entry)
        print(json.dumps(dict(key=key,dimensions=entry['dimensions'],triangles=entry['visualImport']['triangles'])),flush=True)


def thumbnails():
    from tools.render_industrial_asset_thumbnail import render_industrial_asset_thumbnail
    for item in inventory():
        target=ROOT/item['target']
        evidence=target/'thumbnail-evidence.json'
        if evidence.exists():
            prior=json.loads(evidence.read_bytes())
            if prior.get('passed') and prior.get('renderer',{}).get('threeRevision')=='184' and prior.get('source',{}).get('sha256')==base.sha(target/'model-display.glb'):
                continue
        for attempt in range(3):
            try:
                render_industrial_asset_thumbnail(target/'model-display.glb',target/'thumbnail.webp',
                    evidence_path=evidence,width=640,height=480,background='#eef3f7')
                break
            except Exception as error:
                if attempt==2 or 'ERR_ABORTED' not in str(error):raise
        print('Rendered '+item['displayName'],flush=True)


if __name__=='__main__':
    thumbnails() if 'thumbnails' in sys.argv else prepare()
