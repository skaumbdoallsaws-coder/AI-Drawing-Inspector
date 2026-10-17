"""Measure and stage the supplied patio models without publishing the catalog."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT = ROOT / '.runtime/private-gym-patio-import-20261009'
SOURCE = Path('C:/Users/might/OneDrive/Desktop/additional parts')
ITEMS = [
    ('enclosure', 'Patio Enclosure', 'patio enclosure.STEP'),
    ('grill', 'Outdoor Grill', 'GRILL 1.STEP'),
    ('picnic', 'Picnic Table and Chairs', 'Set of picnic table and chairs.stl'),
    ('drinks', 'Patio Chairs and Drinks', 'Set of chairs with drinks.stl'),
    ('plant', 'Patio Decorative Plant', 'Decorative Plant 3.stl'),
    ('palm', 'Patio Palm Tree', 'palm tree.stl'),
]


def convert():
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for key, name, filename in ITEMS:
        target = base.LIBRARY / ('gym-patio-' + key)
        target.mkdir(parents=True, exist_ok=True)
        source = SOURCE / filename
        if not (target / filename).exists():
            copy2(source, target / filename)
        assert base.sha(source) == base.sha(target / filename)
        item = dict(assetId='asset-gym-patio-' + key, displayName=name, source=filename,
            sourceSha256=base.sha(source), format=source.suffix.lower(), target=target.relative_to(ROOT).as_posix())
        items.append(item)
        receipt = OUT / (item['assetId'] + '-conversion.json')
        if receipt.exists():
            previous = json.loads(receipt.read_text())
            assert previous['sourceSha256'] == item['sourceSha256']
            if previous['status'] == 'converted':
                continue
        result = base.convert_stl(item) if item['format'] == '.stl' else base.convert_interchange(item, True)
        result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT / result['artifact'])
        result.update(status='converted', assetId=item['assetId'], sourceSha256=item['sourceSha256'])
        base.write(receipt, result)
        print(json.dumps(result), flush=True)
    base.write(OUT / 'inventory.json', items)


def inspect():
    import numpy as np
    import trimesh
    report = []
    for key, _, filename in ITEMS:
        target = base.LIBRARY / ('gym-patio-' + key)
        scene = trimesh.load_scene(target / 'model.glb', process=False)
        parts = []
        for node in scene.graph.nodes_geometry:
            matrix, geometry = scene.graph[node]
            mesh = scene.geometry[geometry].copy()
            mesh.apply_transform(matrix)
            if filename.lower().endswith('.stl'):
                mesh.merge_vertices()
                components = mesh.split(only_watertight=False)
            else:
                components = [mesh]
            parts.extend(dict(node=node, triangles=len(p.faces), bounds=p.bounds.tolist()) for p in components)
        report.append(dict(key=key, bounds=scene.bounds.tolist(), parts=parts))
    base.write(OUT / 'geometry-inspection.json', report)
    print(json.dumps([dict(key=r['key'], bounds=r['bounds'], parts=len(r['parts'])) for r in report]))


def normalize():
    import numpy as np
    import trimesh
    from tools.gym_theme_wall import linear_rgb
    from tools.apex_equipment_materials import pack, unpack
    for key, _, filename in ITEMS:
        if not filename.lower().endswith('.stl'):
            continue
        target = base.LIBRARY / ('gym-patio-' + key)
        mesh = trimesh.load_mesh(target / filename, process=False)
        removed = 0
        if key == 'picnic':
            floor = np.all(np.abs(mesh.triangles[:, :, 2] + 21.9927996397) < 1e-4, axis=1)
            assert int(floor.sum()) == 800
            assert np.allclose(np.ptp(mesh.triangles[floor].reshape(-1, 3), axis=0), [600, 600, 0], atol=1e-4)
            removed = int(floor.sum())
            mesh.update_faces(~floor)
            mesh.remove_unreferenced_vertices()
        mesh.apply_scale(.01)
        centers = mesh.triangles_center
        groups = [('furniture', np.ones(len(mesh.faces), dtype=bool), '#777064', .1, .78)]
        if key == 'drinks':
            groups = [('graphite', centers[:, 2] < .37, '#35393E', .15, .7),
                ('gold', centers[:, 2] >= .37, '#C99B39', .25, .58)]
        if key == 'plant':
            leaf = (centers[:, 2] > .59) | ((centers[:, 2] > -.12) & (centers[:, 2] < .12))
            groups = [('foliage', leaf, '#507641', 0, .9), ('stand', ~leaf, '#35393E', .18, .72)]
        if key == 'palm':
            leaf = centers[:, 2] > 1.19
            base_mask = centers[:, 2] < .14
            groups = [('foliage', leaf, '#427044', 0, .85),
                ('trunk', ~leaf & ~base_mask, '#75634B', 0, .92),
                ('base', base_mask, '#555D60', 0, .85)]
        scene = trimesh.Scene()
        for name, mask, color, metal, rough in groups:
            if not mask.any():
                continue
            part = mesh.copy()
            part.update_faces(mask)
            part.remove_unreferenced_vertices()
            part.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
                name='Patio ' + name, baseColorFactor=linear_rgb(color)+[1], metallicFactor=metal,
                roughnessFactor=rough, doubleSided=True))
            scene.add_geometry(part, node_name=name)
        display = target / 'model-display.glb'
        doc, data = unpack(scene.export(file_type='glb'))
        for mat in doc.get('materials', []):
            mat.setdefault('extras', {})['facilityAuthoredFinish'] = True
        display.write_bytes(pack(doc, data))
        base.write(target / 'display-mesh-evidence.json', dict(sourceSha256=base.sha(target / filename),
            removedPresentationPlaneTriangles=removed, sourceTriangles=len(mesh.faces)+removed,
            displayTriangles=len(mesh.faces), displaySha256=base.sha(display),
            geometryPreservedExceptPresentationPlane=True, appearanceBasis='reviewed source regions; decorative finish only'))


def enclosure_parts():
    """Retain every CAD triangle, separating the overhead roof from floor obstacles."""
    import numpy as np
    import trimesh
    from copy import deepcopy
    from tools.apex_equipment_materials import material, pack, unpack
    entry = json.loads((base.LIBRARY / 'gym-patio-enclosure/catalog-entry.json').read_text())
    scene = trimesh.load_scene(ROOT / entry['artifact'], process=False)
    mesh = scene.to_geometry()
    mesh.merge_vertices()
    parts = mesh.split(only_watertight=False)
    lower = [p for p in parts if p.bounds[0, 1] < 2.13359]
    upper = [p for p in parts if p.bounds[0, 1] >= 2.13359]
    assert sum(len(p.faces) for p in lower + upper) == entry['measuredGeometry']['triangles'] == 29900
    offsets, polygons = {}, []
    for key, components in [('supports', lower), ('roof', upper)]:
        merged = trimesh.util.concatenate(components)
        lo, hi = merged.bounds
        offset = np.array([(lo[0]+hi[0])/2, lo[1], (lo[2]+hi[2])/2])
        offsets[key] = offset.tolist()
        merged.apply_translation(-offset)
        merged.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
            baseColorFactor=[53,57,62,255], metallicFactor=.08, roughnessFactor=.8, doubleSided=True))
        raw = merged.export(file_type='glb')
        doc, data = unpack(raw)
        for mat in doc['materials']:
            mat.setdefault('extras', {})['facilityAuthoredFinish'] = True
        target = base.LIBRARY / ('gym-patio-' + key)
        target.mkdir(parents=True, exist_ok=True)
        artifact = target / 'model.glb'
        artifact.write_bytes(pack(doc, data))
        variant = deepcopy(entry)
        variant.update(assetId='asset-gym-patio-'+key, displayName='Patio Pergola '+key.title(),
            artifact=artifact.relative_to(ROOT).as_posix(), sourceToCanonical=np.eye(4).flatten(order='F').tolist(),
            dimensions=dict(zip(('width','height','depth'), (hi-lo).tolist())))
        variant['source']['assemblyPartOf'] = entry['assetId']
        variant['measuredGeometry'] = dict(triangles=len(merged.faces), bounds=merged.bounds.tolist(),
            sourceOffsetMeters=offset.tolist(), sourceSha256=base.sha(artifact))
        if key == 'supports':
            for sx, sz in [(-1,-1),(-1,1),(1,-1),(1,1)]:
                group = [p for p in lower if np.sign(p.centroid[0]-offset[0]) == sx and np.sign(p.centroid[2]-offset[2]) == sz]
                points = np.vstack([p.vertices for p in group])-offset
                a, b = points.min(axis=0), points.max(axis=0)
                polygons.append([dict(x=float(x),z=float(z)) for x,z in [(a[0],a[2]),(b[0],a[2]),(b[0],b[2]),(a[0],b[2])]])
            variant['footprintPolygons'] = polygons
            variant['supportSurfaces'] = [dict(surfaceId='pergola-roof-seat',label='Measured pergola roof assembly interface',
                localFrame=dict(origin=dict(x=0,y=2.1335999965667725,z=0),xAxis=dict(x=1,y=0,z=0),
                    zAxis=dict(x=0,y=0,z=1),normal=dict(x=0,y=1,z=0)),
                bounds=dict(minimumX=-1.8288,maximumX=1.8288,minimumZ=-1.8288,maximumZ=1.8288),
                allowedSides=['above'],evidenceStatus='derived')]
        base.write(target / 'catalog-entry.json', variant)
    assert np.allclose(np.array(offsets['supports'])[[0,2]], np.array(offsets['roof'])[[0,2]], atol=1e-6)
    base.write(OUT / 'enclosure-parts.json',dict(sourceTriangles=29900,allTrianglesRetained=True,offsets=offsets,
        supportFootprints=polygons,qualification='Geometric assembly interface only; structural loads are unverified.'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'inspect', 'normalize', 'prepare', 'parts'])
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    if args.phase == 'convert':
        convert()
    elif args.phase == 'inspect':
        inspect()
    elif args.phase == 'normalize':
        normalize()
    elif args.phase == 'parts':
        enclosure_parts()
    else:
        base.OUT = OUT
        base.prepare(args.review, set())
        for key, _, _ in ITEMS:
            file = base.LIBRARY / ('gym-patio-' + key) / 'catalog-entry.json'
            entry = json.loads(file.read_text())
            entry['category'] = 'Outdoor Furniture'
            entry['tags'] = ['patio', 'outdoor', key]
            entry['description'] = entry['description'].replace('gym equipment', 'patio model').replace(
                'exercise clearances', 'operating clearances')
            base.write(file, entry)
