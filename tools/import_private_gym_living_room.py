"""Import the supplied living-room furniture, excluding only its presentation floor."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.apex_equipment_materials import trimesh, np, unpack, pack, material

OUT = ROOT/'.runtime/private-gym-living-room-20261010'
SOURCE = Path('C:/Users/might/OneDrive/Desktop/additional parts/LIVING ROOM 1.stl')
TARGET = base.LIBRARY/'gym-living-room-1'
ASSET = 'asset-gym-living-room-1'


def convert():
    OUT.mkdir(parents=True,exist_ok=True)
    TARGET.mkdir(parents=True,exist_ok=True)
    if not (TARGET/SOURCE.name).exists():
        copy2(SOURCE,TARGET/SOURCE.name)
    assert base.sha(SOURCE)==base.sha(TARGET/SOURCE.name)
    mesh=trimesh.load_mesh(TARGET/SOURCE.name,process=False)
    source_bounds=mesh.bounds.copy()
    original_faces=len(mesh.faces)
    floor=np.all(np.abs(mesh.triangles[:,:,2]-92.01824188232422)<1e-4,axis=1)
    assert int(floor.sum())==800
    assert np.allclose(np.ptp(mesh.triangles[floor].reshape(-1,3),axis=0),[400,400,0],atol=1e-4)
    mesh.update_faces(~floor)
    mesh.remove_unreferenced_vertices()
    furniture_bounds=mesh.bounds.copy()
    mesh.apply_scale(.0254)
    # The source has no part names or materials; keep a restrained graphite finish.
    mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[53,57,62,255],metallicFactor=0,roughnessFactor=.88,doubleSided=True))
    raw=mesh.export(file_type='glb')
    doc,data=unpack(raw)
    doc['materials']=[material('upholstery')]
    for m in doc['meshes']:
        for p in m['primitives']:
            p['material']=0
    (TARGET/'model.glb').write_bytes(pack(doc,data))
    item=dict(assetId=ASSET,displayName='Living Room 1 - Reception Seating Set',source=SOURCE.name,
        sourceSha256=base.sha(SOURCE),format='.stl',target=TARGET.relative_to(ROOT).as_posix())
    base.write(OUT/'inventory.json',[item])
    base.write(OUT/(ASSET+'-conversion.json'),dict(status='converted',assetId=ASSET,
        sourceSha256=item['sourceSha256'],artifact=(TARGET/'model.glb').relative_to(ROOT).as_posix(),
        sourceBounds=source_bounds.tolist(),furnitureBounds=furniture_bounds.tolist(),sourceTriangles=original_faces,
        removedPresentationPlaneTriangles=800,retainedTriangles=len(mesh.faces),
        units=dict(sourceUnits='unspecified',assumedUnits='in',scaleToMeters=.0254,
            authority='inferred_from_seat_height_and_sofa_width',requiresConfirmation=True)))
    base.write(OUT/'orientation.json',{ASSET:dict(rotation=[-90,0,0],
        note='Source Z-up. Inch interpretation gives approximately 2.82 m sofa width and 0.43 m seat height; not manufacturer-verified.')})
    print(json.dumps(dict(retainedTriangles=len(mesh.faces),furnitureExtentMeters=(furniture_bounds[1]-furniture_bounds[0]).__mul__(.0254).tolist())))


def prepare():
    base.OUT=OUT
    base.prepare(OUT/'orientation.json',{ASSET})
    entry=json.loads((TARGET/'catalog-entry.json').read_bytes())
    entry['category']='Office Furniture'
    entry['description']='Owner-supplied sofa, two armchairs and three tables. Presentation floor excluded; furniture geometry and arrangement retained. Unitless STL provisionally interpreted as inches from seating proportions; physical dimensions require confirmation.'
    entry['tags']=['reception','living room','sofa','armchair','tables','graphite','concept scale']
    base.write(TARGET/'catalog-entry.json',entry)


def publish():
    proof=json.loads((OUT/'asset-review.json').read_bytes())
    assert proof['status']=='passed'
    entry=json.loads((TARGET/'catalog-entry.json').read_bytes())
    assert base.sha(ROOT/entry['artifact'])==proof['artifactSha256']
    manifest=base.LIBRARY/'catalog.json'
    raw=manifest.read_bytes()
    library=json.loads(raw)
    existing=next((a for a in library['assets'] if a['assetId']==ASSET),None)
    if existing:
        assert existing==entry
        return
    backup=OUT/'catalog-before.json'
    if backup.exists():
        assert backup.read_bytes()==raw
    else:
        backup.write_bytes(raw)
    library['assets'].append(entry)
    library['summary']['total']=len(library['assets'])
    assert manifest.read_bytes()==raw
    base.write(manifest,library)
    print('published')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','prepare','publish'])
    args=parser.parse_args()
    {'convert':convert,'prepare':prepare,'publish':publish}[args.phase]()
