"""Inspect new powerlifting and rear-delt CAD before publishing library entries."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT = ROOT/'.runtime/private-gym-powerlifting-20261012'
SOURCE = Path('C:/Users/might/Downloads/Decorative object')
ITEMS = [('bar', 'Loaded Barbell', 'bar.stp'),
         ('rack', 'Loaded Squat Rack', 'SquatRack.stp'),
         ('rear-delt', 'Fly / Rear Delt Machine', 'Fly rear delt.IGS')]


def inventory():
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for key, name, filename in ITEMS:
        target = base.LIBRARY/('gym-powerlifting-'+key)
        target.mkdir(parents=True, exist_ok=True)
        if not (target/filename).exists():
            copy2(SOURCE/filename, target/filename)
        digest = base.sha(SOURCE/filename)
        assert base.sha(target/filename) == digest
        items.append(dict(assetId='asset-gym-powerlifting-'+key, displayName=name,
                          source=filename, sourceSha256=digest, format=Path(filename).suffix.lower(),
                          target=target.relative_to(ROOT).as_posix()))
    base.write(OUT/'inventory.json', items)
    return items


def convert():
    for item in inventory():
        key = item['assetId'].removeprefix('asset-gym-powerlifting-')
        receipt = OUT/(key+'-conversion.json')
        if receipt.exists():
            previous = json.loads(receipt.read_bytes())
            assert previous['sourceSha256'] == item['sourceSha256']
            if previous['status'] == 'converted':
                continue
        print('Converting '+item['displayName'], flush=True)
        try:
            result = base.convert_interchange(item, True)
            result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT/result['artifact'])
            result['status'] = 'converted'
        except Exception as exc:
            result = dict(status='failed', error=str(exc))
        result.update(sourceSha256=item['sourceSha256'])
        base.write(receipt, result)
        print(json.dumps(result), flush=True)


def inspect():
    from tools.apex_equipment_materials import np, trimesh
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    for item in inventory():
        key = item['assetId'].removeprefix('asset-gym-powerlifting-')
        conversion = json.loads((OUT/(key+'-conversion.json')).read_bytes())
        assert conversion['status'] == 'converted', conversion
        target = ROOT/item['target']
        scene = trimesh.load_scene(target/'model.glb', process=False)
        records = []
        for node in scene.graph.nodes_geometry:
            matrix, name = scene.graph[node]
            mesh = scene.geometry[name]
            points = trimesh.transform_points(mesh.vertices, matrix)
            records.append(dict(node=node, name=name, triangles=len(mesh.faces),
                                bounds=[points.min(axis=0).tolist(), points.max(axis=0).tolist()]))
        b = np.array([r['bounds'] for r in records])
        lo, hi = b[:,0].min(axis=0), b[:,1].max(axis=0)
        result = dict(assetId=item['assetId'], bounds=[lo.tolist(),hi.tolist()],
                      dimensions=(hi-lo).tolist(), triangles=sum(r['triangles'] for r in records), components=records)
        base.write(OUT/(key+'-geometry.json'), result)
        render_software_thumbnail(target/'model.glb', OUT/(key+'-source.webp'), maximum_triangles=1000000)
        print(json.dumps({k:v for k,v in result.items() if k != 'components'}), flush=True)


def prepare():
    from functools import partial
    from io import BytesIO
    from tools.apex_equipment_materials import np, trimesh, annotate, material, unpack, pack
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    import publish_local_machine_library as publisher
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES = 0
    publisher.render_software_thumbnail = partial(render_software_thumbnail, maximum_triangles=500000)
    for item in inventory():
        key = item['assetId'].removeprefix('asset-gym-powerlifting-')
        conversion = json.loads((OUT/(key+'-conversion.json')).read_bytes())
        assert conversion['status'] == 'converted' and conversion['sourceFaces'] == conversion['meshedFaces']
        target = ROOT/item['target']
        raw = (target/'model.glb').read_bytes()
        doc, _ = unpack(raw)
        overrides = {}
        for i, mesh in enumerate(doc['meshes']):
            name = mesh['name']
            for j, primitive in enumerate(mesh['primitives']):
                role = 'frame'
                if key in ('bar', 'rack'):
                    if name == 'schijf':
                        role = 'gold' if primitive['material'] == (6 if key == 'bar' else 12) else 'rubber'
                    elif name in ('stang', 'bus') or name.startswith(('DIN', 'ASME', 'BS 290')):
                        role = 'steel'
                    elif name in ('pin', 'rol', 'ring', 'strip', 'pro3', 'kapbout'):
                        role = 'gold'
                    elif name in ('wood', 'kap'):
                        role = 'rubber'
                else:
                    if name in ('Back seat', 'Seat'):
                        role = 'upholstery'
                    elif name in ('Handle wing', 'Circle', 'Knobe', 'Connecting flange', 'Achievr Paint spray'):
                        role = 'gold'
                    elif name in ('Guide rod', 'Weight lifting rod', 'Bolt', 'Nut') or name.startswith('cr pan'):
                        role = 'steel'
                    elif name in ('Handle Grip', 'End cap', 'Weight Plate'):
                        role = 'rubber'
                overrides[f'{i}:{j}'] = role
        colored, assignments = annotate(raw, overrides)
        scene = trimesh.load_scene(BytesIO(colored), file_type='glb', process=False)
        rotation = np.eye(4)
        if key in ('bar', 'rack'):
            # Source bar axis is Z and the rack's working side is +X.
            rotation[:3,:3] = [[0,0,1],[0,1,0],[-1,0,0]]
        parts, records = [], []
        for node in scene.graph.nodes_geometry:
            matrix, name = scene.graph[node]
            mesh = scene.geometry[name].copy()
            mesh.apply_transform(rotation@matrix)
            bounds = mesh.bounds.copy()
            count, reduced = len(mesh.faces), mesh
            # Bound silhouette and area changes; keep every source component.
            if count > 2500:
                welded = mesh.copy()
                welded.merge_vertices()
                for fraction in (.08, .16, .3, .5):
                    candidate = welded.simplify_quadric_decimation(face_count=max(600,int(count*fraction)), aggression=4)
                    if (np.max(np.abs(candidate.bounds-bounds)) <= .001
                            and abs(candidate.area-mesh.area)/max(mesh.area,1e-12) <= .025):
                        reduced = candidate
                        break
            role = mesh.visual.material.name.removeprefix('APEX ')
            records.append(dict(node=node, name=name, role=role, sourceTriangles=count,
                                displayTriangles=len(reduced.faces),
                                maximumBoundsChangeMeters=float(np.max(np.abs(reduced.bounds-bounds))),
                                relativeSurfaceAreaChange=float(abs(reduced.area-mesh.area)/max(mesh.area,1e-12))))
            parts.append((reduced,role,bounds))
        b = np.array([bounds for _,_,bounds in parts])
        lo,hi = b[:,0].min(axis=0),b[:,1].max(axis=0)
        offset = np.array([-(lo[0]+hi[0])/2,-lo[1],-(lo[2]+hi[2])/2])
        groups = {}
        for mesh,role,_ in parts:
            mesh.apply_translation(offset)
            groups.setdefault(role,[]).append(mesh)
        display = trimesh.Scene()
        for role,meshes in groups.items():
            mesh = trimesh.util.concatenate(meshes)
            mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
            display.add_geometry(mesh,node_name=role,geom_name=role)
        doc,data = unpack(display.export(file_type='glb',include_normals=True))
        for i,mat in enumerate(doc['materials']):
            doc['materials'][i] = material(mat['name'].removeprefix('APEX '))
        artifact = target/'model-display.glb'
        artifact.write_bytes(pack(doc,data))
        description = ('User-supplied CAD at native unit-converted scale, with an APEX black-and-gold display finish. '
                       'Original CAD and complete GLB retained. Installation, load ratings and operating clearances unverified.')
        source = publisher.SourceAsset(item['assetId'], 'APEX '+item['displayName'], 'Facilities', item['source'],
            'interchange', description, ('gym','fitness','APEX','strength',key), (0,0,0))
        entry = publisher._catalog_entry(source,target/item['source'],artifact,target)
        entry['source'].update(format=item['format'].lstrip('.'),unitInterpretation=conversion['units'])
        # Keep the collision footprint at the full-detail CAD bounds.
        entry['dimensions'] = dict(zip(('width','height','depth'),(hi-lo).tolist()))
        entry['sourceToCanonical'] = np.eye(4).flatten(order='F').tolist()
        entry['visualImport'] = dict(sourceSha256=base.sha(target/'model.glb'),displaySha256=base.sha(artifact),
            sourceTriangles=sum(r['sourceTriangles'] for r in records),displayTriangles=sum(r['displayTriangles'] for r in records),
            nativeScalePreserved=True,allComponentsRetained=True,sourceFaces=conversion['sourceFaces'],meshedFaces=conversion['meshedFaces'],
            sourceRotationMatrix=rotation.tolist(),sourceOffset=offset.tolist(),parts=records,materialAssignments=assignments)
        base.write(target/'catalog-entry.json',entry)
        print(json.dumps(dict(assetId=item['assetId'],dimensions=entry['dimensions'],
                             sourceTriangles=entry['visualImport']['sourceTriangles'],
                             displayTriangles=entry['visualImport']['displayTriangles'])),flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'inspect', 'prepare'])
    globals()[parser.parse_args().phase]()
