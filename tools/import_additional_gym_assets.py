"""Stage, review, and publish additional user-supplied gym models."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.runtime/additional-gym-import-20261004'
SOURCE = Path('C:/Users/might/Downloads/more gym eequipment')
LIBRARY = ROOT / 'generated/industrial_assets/local_library'
DEPS = ROOT / '.runtime/model-import-20261002'
sys.path[:0] = [str(ROOT), str(ROOT / 'tools'),
               *([str(Path.home() / 'AppData/Roaming/Python/Python314/site-packages')] if sys.version_info[:2] == (3,14) else []),
               str(DEPS / 'mesh-dependencies'), str(DEPS / 'dependencies')]
ITEMS = [
    ('assembly-1', 'Gym Equipment Assembly', 'Assem1 (1).STEP'),
    ('abdominal-bench', 'Fixed Abdominal Bench', 'Banco Abdominales fijo.IGS'),
    ('flat-bench', 'Flat Exercise Bench', 'BANCO PLANO ENSAMBLE COMPLETO.SLDPRT'),
    ('pull-up-station', 'Multifunction Pull-Up Station', 'Barra Dominadas multifunci\u00f3n.IGS'),
    ('belt-squat', 'Belt Squat Machine', 'BELT SQUAT COMPLETED.SLDPRT'),
    ('ef-000', 'EF-000 Exercise Machine', 'EF-000.SLDPRT'),
    ('leg-extension', 'Leg Extension Machine', 'Femoral Extension.SLDPRT'),
    ('floor-glute-ham', 'Floor Glute-Ham Bench', 'FLOOR GLUTE HAM.SLDPRT'),
    ('full-station', 'Gym Station Assembly', 'full.STEP'),
    ('equipment-station', 'Gym Equipment Station', 'gym_equipment.STEP'),
    ('hyperextension', 'Hyperextension Bench', 'HIPEREXTENSION COMPLETO.SLDPRT'),
    ('hpz-000', 'HPZ-000 Gym Machine', 'HPZ-000-00.stp'),
    ('leg-curl', 'Leg Curl Machine', 'leg curl.stl'),
    ('squat-calf', 'Squat and Calf Machine', 'Machine Sentadilla Gemelo.IGS'),
    ('preacher-curl', 'Preacher Curl Bench', 'P-000 Predicador Ensamble Completo.SLDPRT'),
    ('pbp-000', 'PBP-000 Exercise Machine', 'PBP-000.SLDPRT'),
    ('standing-pendulum-press', 'Standing Pendulum Press', 'Prensa Pendulo Parado Complete.SLDPRT'),
    ('shoulder-press', 'Shoulder Press Machine', 'Shoulders Machine.SLDPRT'),
    ('sissy-squat', 'Sissy Squat Machine', 'SISSY SQUAT MACHINE.SLDPRT'),
    ('treadmill', 'Treadmill', 'TREAD MILL-.stp'),
    ('cybex-710t', 'Cybex 710T Treadmill', 'Treadmill - Cybex 710T.SLDPRT'),
]


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def layout_hashes():
    folder = ROOT / '.runtime/facility-layout/layouts/local/site-local/layouts'
    return {p.name: sha(p) for p in folder.glob('*.json')}


def inventory():
    OUT.mkdir(parents=True, exist_ok=False)
    catalog = json.loads((LIBRARY / 'catalog.json').read_text())
    originals = {p.name: sha(p) for p in SOURCE.iterdir() if p.is_file()}
    known = {e.get('source', {}).get('sha256'): e['assetId'] for e in catalog['assets']}
    items = []
    for slug, name, filename in ITEMS:
        aid = 'asset-gym-expansion-' + slug
        assert originals[filename] not in known, filename
        known[originals[filename]] = aid
        target = LIBRARY / aid.removeprefix('asset-')
        assert not target.exists(), target
        target.mkdir()
        shutil.copy2(SOURCE / filename, target / filename)
        items.append(dict(assetId=aid, displayName=name, source=filename,
                          sourceSha256=originals[filename], format=Path(filename).suffix.lower(),
                          target=target.relative_to(ROOT).as_posix()))
    skipped = [{ 'file': name, 'duplicateOf': known[digest] }
               for name, digest in originals.items() if name not in {i['source'] for i in items}]
    write(OUT / 'inventory.json', items)
    write(OUT / 'before.json', dict(catalogSha256=sha(LIBRARY / 'catalog.json'),
                                   sources=originals, layouts=layout_hashes(), duplicates=skipped))
    shutil.copy2(LIBRARY / 'catalog.json', OUT / 'catalog-before.json')
    print(json.dumps(dict(newCandidates=len(items), duplicates=skipped)), flush=True)


def convert_interchange(item, retry_failed_faces=False, negligible_face_area_mm2=.000001):
    assert math.isfinite(negligible_face_area_mm2) and 0 <= negligible_face_area_mm2 <= .01
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.IGESCAFControl import IGESCAFControl_Reader
    from OCP.Interface import Interface_Static
    from OCP.Message import Message_ProgressRange
    from OCP.RWGltf import RWGltf_CafWriter
    from OCP.RWMesh import RWMesh_CoordinateSystem_Yup
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_AsciiString, TCollection_ExtendedString
    from OCP.TColStd import TColStd_IndexedDataMapOfStringString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.BRep import BRep_Tool
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    from OCP.TopoDS import TopoDS
    from OCP.TopLoc import TopLoc_Location
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    target = ROOT / item['target']
    iges = item['format'] in {'.igs', '.iges'}
    reader = IGESCAFControl_Reader() if iges else STEPCAFControl_Reader()
    assert Interface_Static.SetCVal_s('xstep.cascade.unit', 'MM')
    reader.SetColorMode(True)
    reader.SetNameMode(True)
    assert reader.ReadFile(str(target / item['source'])) == IFSelect_RetDone
    units = dict(cadKernelUnits='mm', kernelToMeters=0.001, authority='CAD_reader_unit_conversion')
    if iges:
        header = reader.IGESModel().GlobalSection()
        units.update(sourceUnitFlag=header.UnitFlag(), readerUnitValue=header.UnitValue(),
                     sourceUnits=header.UnitName().ToCString())
        if units['sourceUnits'].upper() == 'MM':
            units['sourceUnitMeters'] = .001
    doc = TDocStd_Document(TCollection_ExtendedString('MDTV-XCAF'))
    assert reader.Transfer(doc)
    tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    labels = TDF_LabelSequence()
    tool.GetFreeShapes(labels)
    assert labels.Length() > 0
    face_count = meshed_count = 0
    negligible_faces = []
    missing_faces = []
    for index in range(1, labels.Length()+1):
        shape = tool.GetShape_s(labels.Value(index))
        mesher = BRepMesh_IncrementalMesh(shape, 0.25, False, 0.25, True)
        assert mesher.IsDone()
        faces = TopExp_Explorer(shape, TopAbs_FACE)
        while faces.More():
            face_count += 1
            triangulation = BRep_Tool.Triangulation_s(TopoDS.Face_s(faces.Current()), TopLoc_Location())
            if retry_failed_faces and (triangulation is None or triangulation.NbTriangles() == 0):
                BRepMesh_IncrementalMesh(faces.Current(), 0.05, False, 0.1, False)
                triangulation = BRep_Tool.Triangulation_s(TopoDS.Face_s(faces.Current()), TopLoc_Location())
            if triangulation is not None and triangulation.NbTriangles() > 0:
                meshed_count += 1
            else:
                properties = GProp_GProps()
                BRepGProp.SurfaceProperties_s(TopoDS.Face_s(faces.Current()), properties)
                area = abs(properties.Mass())
                if area <= negligible_face_area_mm2:
                    negligible_faces.append(dict(index=face_count, areaSquareMillimeters=area))
                else:
                    missing_faces.append(dict(index=face_count, areaSquareMillimeters=area))
            faces.Next()
    assert face_count > 0 and meshed_count + len(negligible_faces) == face_count, f'Only {meshed_count}/{face_count} faces meshed; missing: {missing_faces}'
    glb = target / 'model.glb'
    writer = RWGltf_CafWriter(TCollection_AsciiString(str(glb)), True)
    writer.SetMergeFaces(True)
    converter = writer.ChangeCoordinateSystemConverter()
    converter.SetInputCoordinateSystem(RWMesh_CoordinateSystem_Yup)
    converter.SetOutputCoordinateSystem(RWMesh_CoordinateSystem_Yup)
    converter.SetInputLengthUnit(.001)
    converter.SetOutputLengthUnit(1)
    assert writer.Perform(doc, TColStd_IndexedDataMapOfStringString(), Message_ProgressRange())
    return dict(artifact=glb.relative_to(ROOT).as_posix(), roots=labels.Length(),
                sourceFaces=face_count, meshedFaces=meshed_count, negligibleFaces=negligible_faces, units=units,
                negligibleFaceAreaLimitSquareMillimeters=negligible_face_area_mm2)


def convert_stl(item):
    import numpy as np
    import trimesh
    target = ROOT / item['target']
    mesh = trimesh.load_mesh(target / item['source'], process=False)
    bounds = mesh.bounds.copy()
    assert len(mesh.faces) and np.isfinite(mesh.vertices).all()
    # Unitless STL is retained as provisional until independently measured.
    mesh.apply_scale(.01)
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[105,125,137,255], metallicFactor=.15, roughnessFactor=.65, doubleSided=True))
    glb = target / 'model.glb'
    glb.write_bytes(mesh.export(file_type='glb'))
    return dict(artifact=glb.relative_to(ROOT).as_posix(), sourceBounds=bounds.tolist(),
                sourceTriangles=len(mesh.faces), units=dict(sourceUnits='unspecified', assumedUnits='cm',
                scaleToMeters=.01, authority='inferred_from_human_scale_geometry', requiresConfirmation=True))


def convert(kind, selected):
    items = json.loads((OUT / 'inventory.json').read_text())
    for item in items:
        if selected and item['assetId'] not in selected:
            continue
        native = item['format'] == '.sldprt'
        if native != (kind == 'native'):
            continue
        receipt = OUT / (item['assetId'] + '-conversion.json')
        if receipt.exists() and json.loads(receipt.read_text()).get('status') == 'converted':
            continue
        started = time.monotonic()
        print('START ' + item['displayName'], flush=True)
        result = dict(assetId=item['assetId'], sourceSha256=item['sourceSha256'])
        try:
            if native:
                target = ROOT / item['target']
                if not all((target / name).exists() for name in ('native-export.json','model_body.glb','model_process_bodies.json')):
                    with (target / 'extractor.log').open('w', encoding='utf-8') as log:
                        process = subprocess.run([str(OUT / 'bin/AdditionalGymPartExporter.exe'),
                            str(target / item['source']), str(target)], stdout=log, stderr=subprocess.STDOUT,
                            timeout=300, creationflags=subprocess.CREATE_NO_WINDOW)
                    assert process.returncode == 0, f'Native export failed: {process.returncode}'
                assert sha(target / item['source']) == item['sourceSha256']
                evidence = json.loads((target / 'native-export.json').read_text(encoding='utf-8-sig'))
                body_data = json.loads((target / 'model_process_bodies.json').read_text(encoding='utf-8-sig'))
                bodies = body_data['bodies']
                assert len(bodies) == evidence['visibleBodies'], 'Visible bodies missing from export'
                assert sum(b['faceCount'] for b in bodies) == evidence['visibleFaces'], 'Faces missing from export'
                result.update(artifact=(target / 'model_body.glb').relative_to(ROOT).as_posix(),
                    nativeEvidence=evidence, units=dict(sourceUnits='m', authority='SolidWorks_API_meters'),
                    appearance='Body palette; source CAD appearance retained in original file')
            else:
                result.update(convert_stl(item) if item['format'] == '.stl' else convert_interchange(item))
            result.update(status='converted', bytes=(ROOT / result['artifact']).stat().st_size)
        except Exception as exc:
            traceback.print_exc()
            result.update(status='failed', error=str(exc))
        result['seconds'] = round(time.monotonic()-started, 2)
        write(receipt, result)
        print(json.dumps(result), flush=True)


def prepare(review_path, selected, gpu=False):
    import numpy as np
    import trimesh
    import publish_local_machine_library as publisher
    from functools import partial
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES = (1 << 50) if gpu else 0
    publisher.render_software_thumbnail = partial(publisher.render_software_thumbnail, maximum_triangles=2000000)
    if gpu:
        renderer = publisher.render_industrial_asset_thumbnail

        def checked_render(glb, thumbnail, **options):
            evidence_path = options['evidence_path']
            if evidence_path.exists() and thumbnail.exists():
                cached = json.loads(evidence_path.read_text())
                if (cached.get('passed') and cached.get('checks', {}).get('inputTransferFinished')
                    and cached.get('source', {}).get('sha256') == sha(glb)
                    and cached.get('output', {}).get('sha256') == sha(thumbnail)
                    and cached.get('renderer', {}).get('sourceTransform') == options.get('source_transform')):
                    return cached
            for attempt in range(3):
                try:
                    return renderer(glb, thumbnail, **options)
                except Exception as error:
                    transient = any(word in str(error) for word in ('ERR_ABORTED', 'browser has been closed', 'TargetClosed'))
                    if attempt == 2 or not transient:
                        raise
                    print('Retrying transient headless preview transfer', flush=True)
                    time.sleep(.5)

        publisher.render_industrial_asset_thumbnail = checked_render
    review = json.loads(review_path.read_text()) if review_path else {}
    for item in json.loads((OUT / 'inventory.json').read_text()):
        aid = item['assetId']
        if selected and aid not in selected:
            continue
        path = OUT / (aid + '-conversion.json')
        if not path.exists():
            continue
        result = json.loads(path.read_text())
        if result['status'] != 'converted':
            continue
        target = ROOT / item['target']
        glb = ROOT / result['artifact']
        if (target / 'model-display.glb').exists():
            glb = target / 'model-display.glb'
        units = result['units']
        if units.get('sourceUnits', '').upper() == 'MM':
            if 'readerUnitValue' not in units:
                units['readerUnitValue'] = units.get('sourceUnitMeters')
            units['sourceUnitMeters'] = .001
            write(path, result)
        decision = review.get(aid, {})
        rotation = tuple(decision.get('rotation', [0,0,0]))
        name = decision.get('name', item['displayName'])
        description = ('User-supplied gym equipment. CAD-derived geometry; exercise clearances, '
                       'installation requirements and load ratings are unverified.')
        if result['units'].get('requiresConfirmation'):
            description += ' Unitless STL interpreted as centimetres; scale requires confirmation.'
        if decision.get('note'):
            description += ' ' + decision['note']
        source = publisher.SourceAsset(aid, name, 'Facilities', item['source'],
            'part' if item['format'] == '.sldprt' else 'interchange', description,
            ('gym', 'fitness', 'commercial gym', *name.lower().split()), rotation)
        entry = publisher._catalog_entry(source, target / item['source'], glb, target)
        scene = trimesh.load_scene(glb, process=False)
        matrix = np.asarray(publisher._rotation_matrix_xyz_degrees(rotation)).reshape((4,4), order='F')
        bounds = []
        triangles = 0
        for node in scene.graph.nodes_geometry:
            world, geometry = scene.graph[node]
            mesh = scene.geometry[geometry]
            points = trimesh.transform_points(mesh.vertices, matrix @ world)
            assert np.isfinite(points).all()
            bounds.append([points.min(axis=0), points.max(axis=0)])
            triangles += len(mesh.faces)
        lo, hi = np.min(np.array(bounds)[:,0],axis=0), np.max(np.array(bounds)[:,1],axis=0)
        dimensions = hi-lo
        assert all(math.isfinite(x) and x > .01 for x in dimensions)
        translation = np.eye(4)
        translation[:3,3] = [-(lo[0]+hi[0])/2, -lo[1], -(lo[2]+hi[2])/2]
        entry['sourceToCanonical'] = publisher._matrix4_multiply(translation.flatten(order='F').tolist(), matrix.flatten(order='F').tolist())
        entry['dimensions'] = dict(zip(('width','height','depth'),dimensions.tolist()))
        entry['source'].update(format=item['format'].lstrip('.'), unitInterpretation=result['units'])
        entry['measuredGeometry'] = dict(method='full_resolution_transformed_vertices', bounds=[lo.tolist(),hi.tolist()],
                                       triangles=triangles, sourceSha256=sha(glb))
        if (target / 'display-mesh-evidence.json').exists():
            entry['visualImport'] = json.loads((target / 'display-mesh-evidence.json').read_text())
        if 'appearance' in result:
            entry['description'] += ' Neutral display finish; original CAD retained.'
        write(target / 'catalog-entry.json', entry)
        print(json.dumps(dict(assetId=aid, name=name, dimensions=entry['dimensions'], triangles=triangles)), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['inventory','convert','prepare','gpu'])
    parser.add_argument('--kind', choices=['interchange','native'], default='interchange')
    parser.add_argument('--review', type=Path)
    parser.add_argument('--asset', action='append', default=[])
    args = parser.parse_args()
    if args.phase == 'inventory':
        inventory()
    elif args.phase == 'convert':
        convert(args.kind, set(args.asset))
    else:
        prepare(args.review, set(args.asset), args.phase == 'gpu')
