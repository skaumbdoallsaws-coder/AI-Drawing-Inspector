"""Inspect the supplied table games and billiard accessories before publication."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT = ROOT/'.runtime/private-gym-table-games-20261012'
SOURCE = Path('C:/Users/might/Downloads/Decorative object')
ITEMS = [('foosball', 'Full Size Table Football', 'table football.stp'),
         ('blackjack', 'Blackjack Table', 'BlackJackTable.SLDPRT'),
         ('organizer', 'Pool Cue and Ball Organizer', 'pool organizer.STEP'),
         ('balls', 'Pool Balls', 'pool ball.stl')]
A = 'asset-gym-table-games-'


def inventory():
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    for key, name, filename in ITEMS:
        target = base.LIBRARY/('gym-table-games-'+key)
        target.mkdir(parents=True, exist_ok=True)
        if not (target/filename).exists():
            copy2(SOURCE/filename, target/filename)
        digest = base.sha(SOURCE/filename)
        assert base.sha(target/filename) == digest
        items.append(dict(assetId=A+key, displayName=name, source=filename,
                          sourceSha256=digest, format=Path(filename).suffix.lower(),
                          target=target.relative_to(ROOT).as_posix()))
    base.write(OUT/'inventory.json', items)
    return items


def convert():
    for item in inventory():
        key = item['assetId'].removeprefix(A)
        if key == 'balls':
            continue
        receipt = OUT/(key+'-conversion.json')
        if receipt.exists():
            previous = json.loads(receipt.read_bytes())
            assert previous['sourceSha256'] == item['sourceSha256']
            if previous['status'] == 'converted':
                continue
        target = ROOT/item['target']
        print('Converting '+item['displayName'], flush=True)
        if item['format'] == '.sldprt':
            exporter = ROOT/'.runtime/additional-gym-import-20261004/bin/AdditionalGymPartExporter.exe'
            with (target/'extractor.log').open('w') as log:
                result = subprocess.run([str(exporter), str(target/item['source']), str(target)],
                    stdout=log, stderr=subprocess.STDOUT, timeout=300,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            assert result.returncode == 0, (target/'extractor.log').read_text()
            evidence = json.loads((target/'native-export.json').read_text(encoding='utf-8-sig'))
            bodies = json.loads((target/'model_process_bodies.json').read_text(encoding='utf-8-sig'))['bodies']
            assert len(bodies) == evidence['visibleBodies']
            assert sum(b['faceCount'] for b in bodies) == evidence['visibleFaces']
            copy2(target/'model_body.glb', target/'model.glb')
            result = dict(artifact=(target/'model.glb').relative_to(ROOT).as_posix(),
                nativeEvidence=evidence, units=dict(sourceUnits='m', authority='SolidWorks_API_meters'))
        else:
            result = base.convert_interchange(item, True)
            result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT/result['artifact'])
        assert base.sha(target/item['source']) == item['sourceSha256']
        result.update(status='converted', sourceSha256=item['sourceSha256'])
        base.write(receipt, result)
        print(json.dumps(result), flush=True)


def inspect():
    from tools.apex_equipment_materials import np, trimesh
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    for item in inventory():
        key = item['assetId'].removeprefix(A)
        target = ROOT/item['target']
        if (OUT/(key+'-geometry.json')).exists() and (OUT/(key+'-source.webp')).exists():
            continue
        if key == 'balls':
            mesh = trimesh.load_mesh(target/item['source'], process=True)
            parts = mesh.split(only_watertight=False)
            base.write(OUT/'balls-stl.json', dict(bounds=mesh.bounds.tolist(), triangles=len(mesh.faces),
                components=[dict(faces=len(m.faces),bounds=m.bounds.tolist(),watertight=m.is_watertight) for m in parts]))
            print(json.dumps(dict(key=key,bounds=mesh.bounds.tolist(),components=len(parts))),flush=True)
            continue
        if not (OUT/(key+'-conversion.json')).exists():
            continue
        conversion = json.loads((OUT/(key+'-conversion.json')).read_bytes())
        assert conversion['status'] == 'converted'
        scene = trimesh.load_scene(target/'model.glb', process=False)
        records = []
        for node in scene.graph.nodes_geometry:
            matrix, name = scene.graph[node]
            mesh = scene.geometry[name]
            if not isinstance(mesh, trimesh.Trimesh):
                assert len(mesh.vertices) == 1, 'Unexpected non-surface geometry'
                continue
            points = trimesh.transform_points(mesh.vertices, matrix)
            records.append(dict(node=node, name=name, triangles=len(mesh.faces),
                                bounds=[points.min(axis=0).tolist(), points.max(axis=0).tolist()]))
        b = np.array([r['bounds'] for r in records])
        lo, hi = b[:,0].min(axis=0), b[:,1].max(axis=0)
        result = dict(assetId=item['assetId'], bounds=[lo.tolist(),hi.tolist()],
                      dimensions=(hi-lo).tolist(), triangles=sum(r['triangles'] for r in records), components=records)
        base.write(OUT/(key+'-geometry.json'), result)
        render_software_thumbnail(target/'model.glb', OUT/(key+'-source.webp'), maximum_triangles=150000)
        print(json.dumps({k:v for k,v in result.items() if k != 'components'}), flush=True)


def supports():
    from tools.apex_equipment_materials import np, trimesh
    library = json.loads((base.LIBRARY/'catalog.json').read_bytes())
    entry = next(a for a in library['assets'] if a['assetId']=='asset-gym-games-pool')
    scene = trimesh.load_scene(ROOT/entry['artifact'], process=False)
    canonical = np.array(entry['sourceToCanonical']).reshape(4,4).T
    records = []
    for node in scene.graph.nodes_geometry:
        matrix,name = scene.graph[node]
        mesh = scene.geometry[name].copy()
        mesh.apply_transform(canonical@matrix)
        ids = np.flatnonzero(mesh.face_normals[:,1]>.9999)
        levels = {}
        for f in ids:
            y = round(float(mesh.triangles_center[f,1]),6)
            if .5<y<1:
                levels.setdefault(y,[]).append(int(f))
        for y, faces in levels.items():
            area = float(mesh.area_faces[faces].sum())
            if area<.1:
                continue
            points = mesh.triangles[faces].reshape(-1,3)
            records.append(dict(name=name,y=y,area=area,
                bounds=[points.min(axis=0).tolist(),points.max(axis=0).tolist()]))
    base.write(OUT/'pool-supports.json',records)
    print(json.dumps(records),flush=True)


def surfaces():
    from tools.apex_equipment_materials import np, trimesh
    target = base.LIBRARY/'gym-table-games-blackjack'
    scene = trimesh.load_scene(target/'model.glb', process=False)
    records = []
    for node in scene.graph.nodes_geometry:
        matrix,name = scene.graph[node]
        mesh = scene.geometry[name].copy()
        mesh.apply_transform(matrix)
        ids = np.flatnonzero(mesh.face_normals[:,1]>.999)
        levels = {}
        for f in ids:
            levels.setdefault(round(float(mesh.triangles_center[f,1]),6),[]).append(int(f))
        for y,faces in levels.items():
            points = mesh.triangles[faces].reshape(-1,3)
            records.append(dict(name=name,y=y,faces=len(faces),area=float(mesh.area_faces[faces].sum()),
                bounds=[points.min(axis=0).tolist(),points.max(axis=0).tolist()]))
    base.write(OUT/'blackjack-surfaces.json',records)
    print(json.dumps(records),flush=True)


def recover():
    import OCP.BRepMesh as bm
    from OCP.BRep import BRep_Tool
    from OCP.BRepTools import BRepTools
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS
    original = bm.BRepMesh_IncrementalMesh
    attempts = []

    def mesh(shape, *args):
        result = original(shape, *args)
        if shape.ShapeType() != TopAbs_FACE:
            return result
        face = TopoDS.Face_s(shape)
        tri = BRep_Tool.Triangulation_s(face, TopLoc_Location())
        if tri is not None and tri.NbTriangles():
            return result
        for deflection, angle in [(1,.5),(.5,.5),(.1,.5),(.01,.3),(.001,.1),(.0001,.05)]:
            BRepTools.Clean_s(face)
            result = original(face, deflection, False, angle, False)
            tri = BRep_Tool.Triangulation_s(face, TopLoc_Location())
            attempts.append(dict(deflection=deflection,angle=angle,triangles=tri.NbTriangles() if tri else 0))
            if tri is not None and tri.NbTriangles():
                break
        return result

    bm.BRepMesh_IncrementalMesh = mesh
    item = next(i for i in inventory() if i['assetId']==A+'organizer')
    try:
        result = base.convert_interchange(item, True)
        result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted',sourceSha256=item['sourceSha256'],meshingRecovery=attempts)
        base.write(OUT/'organizer-conversion.json',result)
        print(json.dumps(result),flush=True)
    finally:
        bm.BRepMesh_IncrementalMesh = original
        base.write(OUT/'organizer-recovery-attempts.json',attempts)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'inspect', 'supports', 'surfaces', 'recover'])
    globals()[parser.parse_args().phase]()
