"""Prepare the supplied car models with retained originals and explicit scale evidence."""
import argparse
import json
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import import_breakroom_assets as importer

SOURCE = Path(r'C:/Users/might/Downloads/cars')
OUT = ROOT / '.runtime/car-collection-20261003'
STL = 'Lamborghini temerario stl.stl'
REFERENCE = 'https://www.lamborghini.com/original/DAM/lamborghini/0_facelift_2025/model_details_new/temerario_2/brochure_2026/Lamborghini%20Temerario_DIGITAL_BROCHURE_2026_EN.pdf'
DISPLAY_BOUNDS_TOLERANCE = .003
importer.OUT = OUT
importer.SOURCE = SOURCE
importer.NAME_PREFIX = 'vehicle-collection-'
importer.CATEGORY = 'Vehicles'
importer.DESCRIPTION = 'User-supplied vehicle model. Measured visual geometry; operating and traffic envelopes unverified.'
importer.TAGS = ('car', 'vehicle', 'employee parking')
importer.ITEMS = [('concept', 'Concept Car Assembly', 'concept car assembly.STEP'),
                  ('roadster', 'Tesla Roadster - STEP Assembly', 'Tesla Roadster Car.STEP')]


def mesh_imports():
    sys.path.insert(0, str(ROOT / '.runtime/model-import-20261002/mesh-dependencies'))
    import numpy as np
    import trimesh
    return np, trimesh


def convert():
    importer.convert()
    np, trimesh = mesh_imports()
    mesh = trimesh.load_mesh(SOURCE / STL, process=False)
    original = mesh.bounds.copy()
    assert np.isfinite(mesh.vertices).all() and len(mesh.faces) > 0
    # STL is unitless; both independent horizontal dimensions match the
    # manufacturer's millimetre dimensions, rather than merely looking plausible.
    assert abs(mesh.extents[0] - 4706) < 1 and abs(mesh.extents[1] - 2246) < 1
    mesh.apply_scale(.001)
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[116,130,137,255], metallicFactor=.35, roughnessFactor=.45, doubleSided=True))
    target = importer.LIBRARY / 'vehicle-collection-temerario'
    target.mkdir(exist_ok=False)
    shutil.copy2(SOURCE / STL, target / STL)
    glb = target / 'model.glb'
    glb.write_bytes(mesh.export(file_type='glb'))
    records = json.loads((OUT / 'conversion.json').read_text())
    records.append(dict(assetId='asset-vehicle-collection-temerario', name='Lamborghini Temerario', source=STL,
        sourceSha256=importer.sha(SOURCE / STL), artifact=glb.relative_to(ROOT).as_posix(), bytes=glb.stat().st_size,
        sourceBounds=original.tolist(), sourceTriangles=len(mesh.faces), sourceUnits='unspecified',
        interpretedUnits='mm', scaleToMeters=.001, sourceUnitAuthority='inferred_from_manufacturer_dimensions',
        reference=dict(url=REFERENCE, lengthMm=4706, widthIncludingMirrorsMm=2246, checked='2026-10-03')))
    for record in records:
        scene = trimesh.load_scene(ROOT / record['artifact'], process=False)
        record['convertedBoundsMeters'] = scene.bounds.tolist()
        record['convertedExtentsMeters'] = scene.extents.tolist()
        if record['source'].lower().endswith('.step'):
            record.update(sourceUnits='mm', sourceUnitAuthority='STEP_length_unit_declaration', scaleToMeters=.001)
    importer.write(OUT / 'conversion.json', records)
    print(json.dumps(records), flush=True)


def compact():
    np, trimesh = mesh_imports()
    for record in json.loads((OUT / 'conversion.json').read_text()):
        source = ROOT / record['artifact']
        scene = trimesh.load_scene(source, process=False)
        original = scene.bounds.copy()
        source_faces = sum(len(m.faces) for m in scene.geometry.values())
        errors = []
        for name, mesh in list(scene.geometry.items()):
            if len(mesh.faces) < 2500:
                continue
            merged = mesh.copy()
            merged.merge_vertices()
            for fraction in (.10, .20, .35, .50):
                reduced = merged.simplify_quadric_decimation(face_count=max(1800, int(len(mesh.faces) * fraction)), aggression=4)
                error = float(np.max(np.abs(reduced.bounds - mesh.bounds)))
                if error <= DISPLAY_BOUNDS_TOLERANCE:
                    reduced.visual = mesh.visual.copy()
                    scene.geometry[name] = reduced
                    errors.append(error)
                    break
        error = float(np.max(np.abs(scene.bounds - original)))
        assert error <= DISPLAY_BOUNDS_TOLERANCE
        target = source.parent / 'model-display.glb'
        scene.export(target)
        evidence = dict(sourceSha256=importer.sha(source), sourceTriangles=source_faces,
            displayTriangles=sum(len(m.faces) for m in scene.geometry.values()),
            maximumPartBoundsChangeMeters=max(errors, default=0), maximumSceneBoundsChangeMeters=error,
            displayBoundsToleranceMeters=DISPLAY_BOUNDS_TOLERANCE,
            sourcePreserved=True, perPartAppearancePreserved=True)
        importer.write(source.parent / 'display-mesh-evidence.json', evidence)
        print(json.dumps(dict(assetId=record['assetId'], **evidence)), flush=True)


def prepare(rotations):
    importer.prepare(rotations)
    import publish_local_machine_library as publisher
    np, trimesh = mesh_imports()
    orientations = json.loads(rotations.read_text()) if rotations else {}
    entries = json.loads((OUT / 'entries.json').read_text())
    records = {r['assetId']: r for r in json.loads((OUT / 'conversion.json').read_text())}
    for entry in entries:
        r = records[entry['assetId']]
        rotation = publisher._rotation_matrix_xyz_degrees(orientations.get(entry['assetId'], [0, 0, 0]))
        matrix = np.array(rotation).reshape((4, 4), order='F')
        scene = trimesh.load_scene(ROOT / r['artifact'], process=False)
        bounds = []
        # Transformed bounding-box corners overestimate rotated assembly parts.
        # Full-resolution vertices define both the footprint and wheel grounding.
        for node in scene.graph.nodes_geometry:
            world, geometry = scene.graph[node]
            points = trimesh.transform_points(scene.geometry[geometry].vertices, matrix @ world)
            bounds.append([points.min(axis=0), points.max(axis=0)])
        lo = np.min(np.array(bounds)[:, 0], axis=0)
        hi = np.max(np.array(bounds)[:, 1], axis=0)
        translation = np.eye(4)
        translation[:3, 3] = [-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2]
        entry['sourceToCanonical'] = publisher._matrix4_multiply(translation.flatten(order='F').tolist(), rotation)
        entry['dimensions'] = dict(zip(('width', 'height', 'depth'), (hi - lo).tolist()))
        entry['measuredGeometry'] = dict(method='full_resolution_transformed_vertices',
            rotatedBoundsMeters=[lo.tolist(), hi.tolist()], sourceSha256=importer.sha(ROOT / r['artifact']))
        entry['source']['format'] = Path(r['source']).suffix.lower().lstrip('.')
        entry['source']['unitInterpretation'] = dict(sourceUnits=r['sourceUnits'], interpretedUnits='mm',
            scaleToMeters=.001, authority=r['sourceUnitAuthority'])
        if 'reference' in r:
            entry['source']['unitInterpretation']['reference'] = r['reference']
            entry['description'] += ' Unitless STL interpreted as millimetres using manufacturer length and mirror width.'
        entry['description'] += ' Original source and full-resolution GLB retained.'
        entry['description'] = entry['description'].replace(' Original STEP and full GLB retained.', '')
        entry['description'] = entry['description'].replace(' original STEP and full GLB retained.', ' original source retained.')
        importer.write((ROOT / entry['artifact']).parent / 'catalog-entry.json', entry)
    importer.write(OUT / 'entries.json', entries)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'compact', 'prepare'])
    parser.add_argument('--rotations', type=Path)
    args = parser.parse_args()
    if args.phase == 'convert': convert()
    elif args.phase == 'compact': compact()
    else: prepare(args.rotations)
