"""Stage the three approved outdoor decorations; never publish the library here."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT = ROOT/'.runtime/private-gym-decorations-20261011'
SOURCE = Path('C:/Users/might/Downloads/Decorative object')
ITEMS = [('bull', 'APEX Bull Sculpture', 'Bull v1.step'),
         ('dog', 'APEX Reclining Dog Sculpture', 'Dog Lying Down v4.step'),
         ('ducati', 'Ducati Monster 796 - APEX Display', 'Ducati monster 796.STEP')]


def inventory():
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for key, name, filename in ITEMS:
        target = base.LIBRARY/('gym-decoration-'+key)
        target.mkdir(parents=True, exist_ok=True)
        source = SOURCE/filename
        if not (target/filename).exists():
            copy2(source, target/filename)
        digest = base.sha(source)
        assert base.sha(target/filename) == digest
        items.append(dict(assetId='asset-gym-decoration-'+key, displayName=name,
                          source=filename, sourceSha256=digest, format='.step',
                          target=target.relative_to(ROOT).as_posix()))
    base.write(OUT/'inventory.json', items)
    return items


def convert(keys):
    for item in inventory():
        if keys and item['assetId'].removeprefix('asset-gym-decoration-') not in keys:
            continue
        receipt = OUT/(item['assetId']+'-conversion.json')
        if receipt.exists():
            previous = json.loads(receipt.read_text())
            assert previous['sourceSha256'] == item['sourceSha256']
            if previous['status'] == 'converted':
                continue
        started = time.monotonic()
        print('Converting '+item['displayName'], flush=True)
        limit = .000001
        if item['assetId'] == 'asset-gym-decoration-ducati':
            # This reviewed source has two sub-tessellation slivers, not missing components.
            assert item['sourceSha256'] == 'ef4584ad510d550422be311da59417b6e3cafb431deb4eaa98bf8543cd46f9eb'
            limit = .003
        result = base.convert_interchange(item, True, negligible_face_area_mm2=limit)
        if item['assetId'] == 'asset-gym-decoration-ducati':
            assert result['sourceFaces'] == 18289
            assert {f['index'] for f in result['negligibleFaces']} == {3288,15401}
            assert sum(f['areaSquareMillimeters'] for f in result['negligibleFaces']) < .003
        result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted', assetId=item['assetId'], sourceSha256=item['sourceSha256'],
                      seconds=round(time.monotonic()-started, 2))
        base.write(receipt, result)
        print(json.dumps(result), flush=True)


def prepare_statues(keys):
    from tools.apex_equipment_materials import np, trimesh, material, unpack, pack
    import publish_local_machine_library as publisher
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES = 0
    publisher.render_software_thumbnail = render_software_thumbnail
    for item in inventory():
        key = item['assetId'].removeprefix('asset-gym-decoration-')
        if key == 'ducati' or (keys and key not in keys):
            continue
        conversion = json.loads((OUT/(item['assetId']+'-conversion.json')).read_text())
        assert conversion['sourceFaces'] == conversion['meshedFaces']
        target = ROOT/item['target']
        scene = trimesh.load_scene(target/'model.glb', process=False)
        parts = []
        for node in scene.graph.nodes_geometry:
            transform, name = scene.graph[node]
            part = scene.geometry[name].copy()
            part.apply_transform(transform)
            parts.append(part)
        sculpture = trimesh.util.concatenate(parts)
        source_triangles = len(sculpture.faces)
        # The CAD tessellation duplicates triangle vertices; share normals on the sculpture.
        sculpture.merge_vertices()
        sculpture.apply_transform(np.array([[1,0,0,0],[0,0,1,0],[0,-1,0,0],[0,0,0,1]]))
        source_size = sculpture.extents.copy()
        factor = 1.3/source_size[1] if key == 'bull' else 1.0
        sculpture.apply_scale(factor)
        lower, upper = sculpture.bounds
        height = .18 if key == 'bull' else .08
        sculpture.apply_translation([-(lower[0]+upper[0])/2, height-lower[1], -(lower[2]+upper[2])/2])
        dimensions = sculpture.extents
        plinth = trimesh.creation.box([dimensions[0]+.3, height, dimensions[2]+.3])
        plinth.apply_translation([0,height/2,0])
        display = trimesh.Scene()
        for mesh, role, name in [(sculpture,'gold','Gold sculpture'),(plinth,'frame','Black display plinth')]:
            mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
            display.add_geometry(mesh, node_name=name, geom_name=name)
        raw = display.export(file_type='glb',include_normals=True)
        doc, data = unpack(raw)
        doc['materials'] = [material(m['name'].removeprefix('APEX ')) for m in doc['materials']]
        (target/'model-display.glb').write_bytes(pack(doc,data))
        assert len(sculpture.faces) == source_triangles
        description = ('User-supplied STEP sculpture with an authored black plinth. '
                       + ('Uniformly enlarged to 1.30 m sculpture height for outdoor display; not a life-size CAD source. '
                          if key == 'bull' else 'Native CAD sculpture scale retained. ')
                       + 'Decorative concept, not installation or anchorage engineering.')
        source = publisher.SourceAsset(item['assetId'], item['displayName'], 'Outdoor Furniture',
            item['source'], 'interchange', description, ('gym','outdoor','decoration','APEX','black and gold'), (0,0,0))
        entry = publisher._catalog_entry(source,target/item['source'],target/'model-display.glb',target)
        entry['source'].update(format='step',unitInterpretation=conversion['units'])
        entry['visualImport'] = dict(nativeGeometryRetained=True,sourceTriangles=source_triangles,
            displayTriangles=source_triangles+len(plinth.faces),sourceToDisplayUniformScale=float(factor),
            sourceDimensionsYUpMeters=source_size.tolist(),sculptureHeightMeters=float(dimensions[1]),
            authoredPlinthHeightMeters=height,sourceAxisRotationDegrees=[-90,0,0],
            sourceSha256=base.sha(target/'model.glb'),displaySha256=base.sha(target/'model-display.glb'),
            roles=['gold','frame'],drawGroups=2)
        base.write(target/'catalog-entry.json',entry)
        print(json.dumps(dict(assetId=item['assetId'],dimensions=entry['dimensions'],importEvidence=entry['visualImport'])),flush=True)


def prepare_ducati(keys):
    from tools.apex_equipment_materials import np, trimesh, material, unpack, pack
    import publish_local_machine_library as publisher
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES = 0
    publisher.render_software_thumbnail = render_software_thumbnail
    item = next(i for i in inventory() if i['assetId'].endswith('-ducati'))
    target = ROOT/item['target']
    conversion = json.loads((OUT/(item['assetId']+'-conversion.json')).read_text())
    assert item['sourceSha256'] == 'ef4584ad510d550422be311da59417b6e3cafb431deb4eaa98bf8543cd46f9eb'
    assert conversion['sourceFaces'] == 18289 and conversion['meshedFaces'] == 18287
    scene = trimesh.load_scene(target/'model.glb', process=False)
    assert len(scene.graph.nodes_geometry) == 25
    gold = {'Frame_Default<As Machined>', 'Front fork_Default<As Machined>',
            'motorcycle front wheel assembly.sldasm-Part-5',
            'motorcycle rear wheel assembly.sldasm-Part-4', 'Levers left', 'Levers right'}
    rubber = {'motorcycle front wheel assembly.sldasm-Part-6',
              'motorcycle rear wheel assembly.sldasm-Part-5'}
    records, parts = [], []
    rotation = trimesh.transformations.rotation_matrix(np.pi/2,[0,1,0])
    for node in scene.graph.nodes_geometry:
        transform, name = scene.graph[node]
        mesh = scene.geometry[name].copy()
        mesh.apply_transform(rotation @ transform)
        original = mesh.bounds.copy()
        count = len(mesh.faces)
        reduced = mesh
        if count >= 2500:
            merged = mesh.copy()
            merged.merge_vertices()
            for fraction in (.10,.20,.35,.50):
                candidate = merged.simplify_quadric_decimation(face_count=max(1800,int(count*fraction)),aggression=4)
                if np.max(np.abs(candidate.bounds-original)) <= .003:
                    reduced = candidate
                    break
        error = float(np.max(np.abs(reduced.bounds-original)))
        role = 'gold' if name in gold else 'rubber' if name in rubber else 'vehicle_paint'
        records.append(dict(node=node,name=name,sourceTriangles=count,displayTriangles=len(reduced.faces),
                            maximumBoundsChangeMeters=error,role=role))
        parts.append((reduced,role))
    bounds = np.array([m.bounds for m,r in parts])
    lo,hi = bounds[:,0].min(axis=0),bounds[:,1].max(axis=0)
    translation = [-(lo[0]+hi[0])/2,-lo[1],-(lo[2]+hi[2])/2]
    display = trimesh.Scene()
    for role in sorted({r for m,r in parts}):
        mesh = trimesh.util.concatenate([m for m,r in parts if r==role])
        mesh.apply_translation(translation)
        mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
        display.add_geometry(mesh,node_name=role,geom_name=role)
    doc,data = unpack(display.export(file_type='glb'))
    doc['materials'] = [material(m['name'].removeprefix('APEX ')) for m in doc['materials']]
    (target/'model-display.glb').write_bytes(pack(doc,data))
    source = publisher.SourceAsset(item['assetId'],item['displayName'],'Outdoor Furniture',item['source'],
        'interchange','User-supplied Ducati STEP, native CAD scale. Black body and tires with gold frame, rims and fork. '
        'Optimized display mesh; original STEP and full-resolution GLB retained. Two source sliver faces '
        'totaling less than 0.003 square millimeters could not be tessellated. Decorative display concept.',
        ('gym','outdoor','motorcycle','APEX','black and gold'),(0,0,0))
    entry = publisher._catalog_entry(source,target/item['source'],target/'model-display.glb',target)
    entry['source'].update(format='step',unitInterpretation=conversion['units'])
    entry['visualImport'] = dict(sourceTriangles=sum(r['sourceTriangles'] for r in records),
        displayTriangles=sum(r['displayTriangles'] for r in records),sourceComponents=25,displayComponentsRetained=25,
        drawGroups=3,parts=records,maximumPartBoundsChangeMeters=max(r['maximumBoundsChangeMeters'] for r in records),
        sourceToDisplayUniformScale=1,sourceAxisRotationDegrees=[0,90,0],canonicalFront='+Z',
        sourceSha256=base.sha(target/'model.glb'),displaySha256=base.sha(target/'model-display.glb'),
        sourceFaces=conversion['sourceFaces'],meshedFaces=conversion['meshedFaces'],
        negligibleFaces=conversion['negligibleFaces'])
    assert entry['visualImport']['displayTriangles'] < 550000
    base.write(target/'catalog-entry.json',entry)
    print(json.dumps(dict(assetId=item['assetId'],dimensions=entry['dimensions'],
                         triangles=entry['visualImport']['displayTriangles'])),flush=True)


def thumbnails(keys):
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    for item in inventory():
        key = item['assetId'].removeprefix('asset-gym-decoration-')
        if keys and key not in keys:
            continue
        target = ROOT/item['target']
        # These bounded display meshes fit without triangle sampling or thumbnail holes.
        render_software_thumbnail(target/'model-display.glb',target/'thumbnail.webp',
            evidence_path=target/'thumbnail-evidence.json',maximum_triangles=550000)
        print('Thumbnail complete: '+key,flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert','prepare-statues','prepare-ducati','thumbnails'])
    parser.add_argument('--key', action='append', default=[])
    args = parser.parse_args()
    {'convert':convert,'prepare-statues':prepare_statues,'prepare-ducati':prepare_ducati,
     'thumbnails':thumbnails}[args.phase](set(args.key))
