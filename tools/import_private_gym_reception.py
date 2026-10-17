"""Stage the supplied reception furniture, excluding its presentation floor."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from tools import import_additional_gym_assets as base

OUT = ROOT / '.runtime/private-gym-reception-import-20261009'
SOURCE = Path('C:/Users/might/OneDrive/Desktop/additional parts/reception set.STL')
ASSET = 'asset-gym-reception-set'
TARGET = base.LIBRARY / 'gym-reception-set'


def convert():
    import numpy as np
    import trimesh
    OUT.mkdir(parents=True, exist_ok=True)
    TARGET.mkdir(parents=True, exist_ok=True)
    if not (TARGET / SOURCE.name).exists():
        copy2(SOURCE, TARGET / SOURCE.name)
    assert base.sha(SOURCE) == base.sha(TARGET / SOURCE.name)
    item = dict(assetId=ASSET, displayName='Reception Furniture Set', source=SOURCE.name,
        sourceSha256=base.sha(SOURCE), format='.stl', target=TARGET.relative_to(ROOT).as_posix())
    receipt = base.convert_stl(item)
    mesh = trimesh.load_mesh(TARGET / SOURCE.name, process=False)
    floor = np.all(np.abs(mesh.triangles[:, :, 2] + 37.077735900878906) < 1e-4, axis=1)
    assert int(floor.sum()) == 800
    assert np.allclose(np.ptp(mesh.triangles[floor].reshape(-1, 3), axis=0), [400, 400, 0], atol=1e-4)
    mesh.update_faces(~floor)
    mesh.remove_unreferenced_vertices()
    mesh.apply_scale(.01)
    mesh.visual = trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[125, 139, 149, 255], metallicFactor=.05, roughnessFactor=.7, doubleSided=True))
    (TARGET / 'model.glb').write_bytes(mesh.export(file_type='glb'))
    receipt.update(status='converted', assetId=ASSET, sourceSha256=item['sourceSha256'],
        removedPresentationPlaneTriangles=800, retainedTriangles=len(mesh.faces))
    base.write(OUT / (ASSET + '-conversion.json'), receipt)
    base.write(OUT / 'inventory.json', [item])
    base.write(OUT / 'orientation-review.json', {ASSET: dict(rotation=[-90, 0, 0],
        note='Source Z-up. Presentation floor excluded; all furniture retained.')})
    print(json.dumps(receipt), flush=True)


def prepare():
    import publish_local_machine_library as publisher
    from tools.render_industrial_asset_software_thumbnail import render_software_thumbnail
    def bounded(*args, **kwargs):
        kwargs['maximum_triangles'] = 400000
        return render_software_thumbnail(*args, **kwargs)
    publisher.render_software_thumbnail = bounded
    base.OUT = OUT
    base.prepare(OUT / 'orientation-review.json', {ASSET})
    entry = json.loads((TARGET / 'catalog-entry.json').read_text())
    entry['category'] = 'Office Furniture'
    entry['tags'] = ['reception', 'desk', 'office', 'gym']
    entry['description'] = ('User-supplied reception furniture; presentation floor removed. '
        'Unitless STL interpreted as centimetres based on desk and monitor proportions; '
        'physical scale requires confirmation.')
    base.write(TARGET / 'catalog-entry.json', entry)


def finish():
    from tools.apex_equipment_materials import build_variant
    entry = json.loads((TARGET / 'catalog-entry.json').read_text())
    # The STL has no reliable part labels; use a cohesive graphite finish.
    overrides = {'0': 'upholstery'}
    raw, evidence = build_variant(entry, overrides)
    (TARGET / 'model-display.glb').write_bytes(raw)
    base.write(TARGET / 'display-mesh-evidence.json', evidence)
    print(json.dumps(dict(triangles=evidence['triangleCount'],
        geometryPreserved=evidence['geometryPreserved'])), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'prepare', 'finish'])
    args = parser.parse_args()
    {'convert': convert, 'prepare': prepare, 'finish': finish}[args.phase]()
