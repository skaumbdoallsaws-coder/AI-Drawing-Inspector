"""Import and inspect user-supplied games and office Bible without publishing."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT = ROOT / '.runtime/private-gym-games-20261011'
SOURCE = Path('C:/Users/might/Downloads/Decorative object')
ITEMS = [
    ('pool', 'Pool Table', 'Pool Table v21.step'),
    ('ps5', 'PlayStation 5 Pro', 'PS5 PRO+ BASE.STEP'),
    ('controller', 'PlayStation Controller', 'PS5_CONTROLLER_3TRY.STEP'),
    ('bible', 'Closed Bible', 'CLOSED BIBLE STEP - EN.stp'),
    ('arcade-kombie', 'Kombie Arcade Cabinet', 'Arcade Cabinet Kombie03 v118.step'),
    ('arcade-small', 'Compact Arcade Cabinet', 'Arcade menor.stp'),
    ('arcade-bartop', 'Bartop Arcade Cabinet', 'Montagem Bartop Donkey Kong.stp'),
]


def inventory():
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for key, name, filename in ITEMS:
        target = base.LIBRARY / ('gym-games-' + key)
        target.mkdir(parents=True, exist_ok=True)
        if not (target / filename).exists():
            copy2(SOURCE / filename, target / filename)
        digest = base.sha(SOURCE / filename)
        assert base.sha(target / filename) == digest
        items.append(dict(assetId='asset-gym-games-' + key, displayName=name,
            source=filename, sourceSha256=digest, format='step',
            target=target.relative_to(ROOT).as_posix()))
    base.write(OUT / 'inventory.json', items)
    return items


def convert():
    for item in inventory():
        key = item['assetId'].removeprefix('asset-gym-games-')
        receipt = OUT / (key + '-conversion.json')
        if receipt.exists():
            previous = json.loads(receipt.read_bytes())
            assert previous['sourceSha256'] == item['sourceSha256']
            if previous['status'] in ('converted', 'failed'):
                continue
        print('Converting ' + item['displayName'], flush=True)
        try:
            result = base.convert_interchange(item, True, negligible_face_area_mm2=.000001)
            result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT / result['artifact'])
            result.update(status='converted', sourceSha256=item['sourceSha256'])
        except Exception as exc:
            result = dict(status='failed', sourceSha256=item['sourceSha256'], error=str(exc))
        base.write(receipt, result)
        print(json.dumps(result), flush=True)


def inspect():
    from tools.apex_equipment_materials import np, trimesh
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    for item in inventory():
        key = item['assetId'].removeprefix('asset-gym-games-')
        target = ROOT / item['target']
        if not (OUT / (key + '-conversion.json')).exists():
            continue
        if json.loads((OUT / (key + '-conversion.json')).read_bytes())['status'] != 'converted':
            continue
        scene = trimesh.load_scene(target / 'model.glb', process=False)
        records = []
        for node in scene.graph.nodes_geometry:
            matrix, name = scene.graph[node]
            mesh = scene.geometry[name]
            points = trimesh.transform_points(mesh.vertices, matrix)
            records.append(dict(node=node, name=name, triangles=len(mesh.faces),
                bounds=[points.min(axis=0).tolist(), points.max(axis=0).tolist()]))
        b = np.array([r['bounds'] for r in records])
        lo, hi = b[:, 0].min(axis=0), b[:, 1].max(axis=0)
        result = dict(assetId=item['assetId'], bounds=[lo.tolist(), hi.tolist()],
            dimensions=(hi-lo).tolist(), triangles=sum(r['triangles'] for r in records), components=records)
        base.write(OUT / (key + '-geometry.json'), result)
        render_software_thumbnail(target / 'model.glb', OUT / (key + '-source.webp'), maximum_triangles=900000)
        print(json.dumps({k:v for k,v in result.items() if k != 'components'}), flush=True)


def supports():
    from tools.apex_equipment_materials import np, trimesh
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    library = json.loads((base.LIBRARY / 'catalog.json').read_bytes())
    for aid in ['asset-gym-additional-tv-unit-gold-bezel', 'asset-gym-living-room-1']:
        entry = next(a for a in library['assets'] if a['assetId'] == aid)
        scene = trimesh.load_scene(ROOT / entry['artifact'], process=False)
        rotation = np.array(entry['sourceToCanonical']).reshape(4, 4).T
        result = []
        output = trimesh.Scene()
        for node in scene.graph.nodes_geometry:
            transform, name = scene.graph[node]
            mesh = scene.geometry[name].copy()
            mesh.apply_transform(rotation @ transform)
            output.add_geometry(mesh)
            faces = np.flatnonzero(mesh.face_normals[:, 1] > .9999)
            levels = {}
            for f in faces:
                y = round(float(mesh.triangles_center[f, 1]), 5)
                if .2 < y < 1.5:
                    levels.setdefault(y, []).append(int(f))
            for y, indices in levels.items():
                area = float(mesh.area_faces[indices].sum())
                if area < .02:
                    continue
                points = mesh.triangles[indices].reshape(-1, 3)
                result.append(dict(name=name, y=y, area=area,
                    bounds=[points.min(axis=0).tolist(), points.max(axis=0).tolist()]))
        base.write(OUT / (aid + '-supports.json'), result)
        artifact = OUT / (aid + '.glb')
        artifact.write_bytes(output.export(file_type='glb'))
        render_software_thumbnail(artifact, OUT / (aid + '.webp'), maximum_triangles=1200000)
        print(json.dumps(dict(assetId=aid, surfaces=result)), flush=True)


def prepare():
    from functools import partial
    from tools.apex_equipment_materials import np, trimesh, material, unpack, pack
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    import publish_local_machine_library as publisher
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES = 0
    publisher.render_software_thumbnail = partial(render_software_thumbnail, maximum_triangles=1200000)
    for item in inventory():
        key = item['assetId'].removeprefix('asset-gym-games-')
        receipt = OUT / (key + '-conversion.json')
        if not receipt.exists() or key in ('arcade-kombie', 'arcade-bartop'):
            continue
        conversion = json.loads(receipt.read_bytes())
        assert conversion['status'] == 'converted' and conversion['sourceFaces'] == conversion['meshedFaces']
        target = ROOT / item['target']
        scene = trimesh.load_scene(target / 'model.glb', process=False)
        rotation = np.eye(4)
        if key in ('pool', 'controller', 'ps5'):
            rotation[:3, :3] = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
        if key == 'bible':
            rotation[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        if key == 'arcade-small':
            rotation[:3, :3] = [[0, 1, 0], [0, 0, 1], [1, 0, 0]]
        parts, records = [], []
        for node in scene.graph.nodes_geometry:
            matrix, name = scene.graph[node]
            mesh = scene.geometry[name].copy()
            mesh.apply_transform(rotation @ matrix)
            role = 'frame'
            if key == 'pool':
                if name in ('Top Skirt', 'Top Skirt_1', 'COMPOUND_3'):
                    role = 'gold'
                elif name == 'Felt':
                    role = 'upholstery'
                elif name == 'Pocket Liners':
                    role = 'rubber'
            elif key == 'ps5':
                if name.startswith('base lado'):
                    role = 'gold'
                elif name == 'PS5.BASE':
                    role = 'vehicle_paint'
            elif key == 'controller':
                suffix = name.removeprefix('PS4_CONTROLLER_3TRY')
                role = 'gold' if suffix in ('_3', '_4', '_5', '_6', '_9', '_11') else 'rubber'
            elif key == 'bible':
                role = {'SOLID': 'gold', 'SOLID_1': 'gold', 'SOLID_2': 'frame', 'SOLID_3': 'ivory', 'SHELL': 'gold'}[name]
            elif key == 'arcade-small':
                if name.startswith(('Letra', 'Controle', 'Frente tela', 'Luminoso')):
                    role = 'gold'
                elif name.startswith('Tubo'):
                    role = 'rubber'
            records.append(dict(name=name, sourceTriangles=len(mesh.faces), role=role))
            parts.append((mesh, role))
        b = np.array([m.bounds for m, _ in parts])
        lo, hi = b[:, 0].min(axis=0), b[:, 1].max(axis=0)
        offset = [-(lo[0]+hi[0])/2, -lo[1], -(lo[2]+hi[2])/2]
        groups = {}
        for mesh, role in parts:
            mesh.apply_translation(offset)
            groups.setdefault(role, []).append(mesh)
        display = trimesh.Scene()
        for role, meshes in groups.items():
            mesh = trimesh.util.concatenate(meshes)
            mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(name='APEX '+role))
            display.add_geometry(mesh, node_name=role, geom_name=role)
        doc, data = unpack(display.export(file_type='glb', include_normals=True))
        for i, mat in enumerate(doc['materials']):
            role = mat['name'].removeprefix('APEX ')
            if role == 'ivory':
                doc['materials'][i] = dict(name='Natural paper', pbrMetallicRoughness=dict(baseColorFactor=[.85, .79, .65, 1], metallicFactor=0, roughnessFactor=.8), doubleSided=True, extras=dict(facilityAuthoredFinish=True))
            else:
                doc['materials'][i] = material(role)
        artifact = target / 'model-display.glb'
        artifact.write_bytes(pack(doc, data))
        description = 'User-supplied STEP CAD at native unit-converted scale. APEX black-and-gold finish. All source faces and components retained.'
        if key == 'controller':
            description += ' Filename says PS5; source components identify a PS4-style controller. Visual prop only; device compatibility is not established.'
        source = publisher.SourceAsset(item['assetId'], 'APEX '+item['displayName'], 'Office & IT', item['source'], 'interchange', description, ('gym', 'games', 'APEX', key), (0, 0, 0))
        entry = publisher._catalog_entry(source, target/item['source'], artifact, target)
        entry['source'].update(format='step', unitInterpretation=conversion['units'])
        entry['visualImport'] = dict(sourceSha256=base.sha(target/'model.glb'), displaySha256=base.sha(artifact), sourceTriangles=sum(r['sourceTriangles'] for r in records), displayTriangles=sum(r['sourceTriangles'] for r in records), nativeScalePreserved=True, sourceFaces=conversion['sourceFaces'], meshedFaces=conversion['meshedFaces'], sourceRotationMatrix=rotation.tolist(), parts=records)
        base.write(target/'catalog-entry.json', entry)
        print(json.dumps(dict(assetId=item['assetId'], dimensions=entry['dimensions'])), flush=True)


def thumbnails():
    from tools.render_industrial_asset_thumbnail import render_industrial_asset_thumbnail
    for key in ('pool', 'ps5', 'controller', 'bible', 'arcade-small'):
        target = base.LIBRARY / ('gym-games-' + key)
        proof = json.loads((target/'thumbnail-evidence.json').read_bytes())
        if proof.get('passed') and proof.get('renderer', {}).get('threeRevision') == '184':
            continue
        render_industrial_asset_thumbnail(target/'model-display.glb', target/'thumbnail.webp',
            evidence_path=target/'thumbnail-evidence.json', width=480, height=300, background='#eef3f7')
        print('Rendered preview ' + key, flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'inspect', 'supports', 'prepare', 'thumbnails'])
    {'convert': convert, 'inspect': inspect, 'supports': supports, 'prepare': prepare, 'thumbnails': thumbnails}[parser.parse_args().phase]()
