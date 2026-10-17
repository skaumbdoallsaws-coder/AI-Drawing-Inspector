"""Import the supplied gym CAD, retaining originals and explicit scale evidence."""
import argparse
import json
from pathlib import Path
import shutil
import sys
import zipfile

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from tools import import_breakroom_assets as importer

SOURCE=Path(r'C:/Users/might/Downloads/gym')
INPUTS=ROOT/'.runtime/gym-import-inputs-20261003'
OUT=ROOT/'.runtime/gym-import-20261003'
ITEMS=[('multi-station','Barbell Squat Rack','Assem8 with pich.STEP'),
       ('bench-press','Bench Press','Bench press.stp'),
       ('flat-bench','Adjustable Exercise Bench','BENCH.STEP'),
       ('weight-rack','Power Rack','rack.stp'),
       ('vertical-leg-press','Vertical Leg Press','Vertical leg Press.STEP'),
       ('x1000','X-1000 Gym Station','X-1000.STEP'),
       ('dumbbell-rack','Dumbbell Rack','dumbbell-rack.STEP')]
importer.OUT=OUT;importer.SOURCE=INPUTS;importer.NAME_PREFIX='gym-'
importer.CATEGORY='Facilities'
importer.DESCRIPTION='User-supplied fitness equipment; CAD-derived dimensions. Operating clearances and installation requirements unverified.'
importer.TAGS=('gym','fitness','employee amenities')
importer.ITEMS=ITEMS


def convert():
    INPUTS.mkdir(parents=True,exist_ok=False)
    originals={p.name:importer.sha(p) for p in SOURCE.iterdir() if p.is_file()}
    for _,_,name in ITEMS[:-1]:shutil.copy2(SOURCE/name,INPUTS/name)
    archive=SOURCE/'dumbbell-rack-2.snapshot.1.zip'
    with zipfile.ZipFile(archive) as z:
        steps=[i for i in z.infolist() if Path(i.filename).suffix.lower() in {'.step','.stp'}]
        assert len(steps)==1 and steps[0].file_size<100_000_000
        (INPUTS/'dumbbell-rack.STEP').write_bytes(z.read(steps[0]))
        for index,item in enumerate(i for i in z.infolist() if i.filename.lower().endswith('.jpg')):
            assert item.file_size<10_000_000
            (INPUTS/f'dumbbell-reference-{index}.jpg').write_bytes(z.read(item))
        archived_member=steps[0].filename
    shutil.copy2(SOURCE/'gym eqipment.stl',INPUTS/'gym eqipment.stl')
    importer.convert()
    importer.write(OUT/'original-sources.json',dict(hashes=originals,
        archiveMember=archived_member,archiveSha256=originals[archive.name]))
    sys.path.insert(0,str(ROOT/'.runtime/model-import-20261002/mesh-dependencies'))
    import numpy as np
    import trimesh
    mesh=trimesh.load_mesh(INPUTS/'gym eqipment.stl',file_type='stl',process=True)
    raw_bounds=mesh.bounds.copy();count=len(mesh.faces)
    # STL has no units. Millimetres yield a plausible 1.99 x 3.36 x 3.11 m frame.
    mesh.apply_scale(.001)
    assert np.isfinite(mesh.vertices).all() and len(mesh.faces)>0
    target=importer.LIBRARY/'gym-multi-gym-stl';target.mkdir(exist_ok=False)
    shutil.copy2(INPUTS/'gym eqipment.stl',target/'gym eqipment.stl')
    mesh.visual=trimesh.visual.TextureVisuals(material=trimesh.visual.material.PBRMaterial(
        baseColorFactor=[116,136,147,255],metallicFactor=.2,roughnessFactor=.7,doubleSided=True))
    glb=target/'model.glb';glb.write_bytes(mesh.export(file_type='glb'))
    records=json.loads((OUT/'conversion.json').read_text())
    records.append(dict(assetId='asset-gym-multi-gym-stl',name='Multi-Gym Frame',source='gym eqipment.stl',
        sourceSha256=importer.sha(INPUTS/'gym eqipment.stl'),artifact=glb.relative_to(ROOT).as_posix(),
        bytes=glb.stat().st_size,sourceTriangles=count,sourceBounds=raw_bounds.tolist(),
        sourceUnits='unspecified',assumedUnits='mm',scaleToMeters=.001,scaleRequiresConfirmation=True))
    importer.write(OUT/'conversion.json',records)
    print(json.dumps(records[-1]),flush=True)


def prepare(rotations,gpu=False):
    if gpu:
        sys.path[:0]=[str(ROOT/'tools')]
        import publish_local_machine_library as publisher
        publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES=1<<50
        orientations=json.loads(rotations.read_text())
        names={slug:name for slug,name,_ in ITEMS}
        entries=[]
        for result in json.loads((OUT/'conversion.json').read_text()):
            aid=result['assetId'];glb=ROOT/result['artifact'];target=glb.parent
            display=target/'model-display.glb'
            asset=publisher.SourceAsset(aid,names.get(aid.removeprefix('asset-gym-'),result['name']),
                importer.CATEGORY,result['source'],'interchange',importer.DESCRIPTION,importer.TAGS,
                tuple(orientations.get(aid,[0,0,0])))
            entry=publisher._catalog_entry(asset,INPUTS/result['source'],display if display.exists() else glb,target)
            if display.exists():entry['visualImport']=json.loads((target/'display-mesh-evidence.json').read_text())
            entries.append(entry)
            print(json.dumps(dict(assetId=aid,dimensions=entry['dimensions'],gpuPassed=True)),flush=True)
        importer.write(OUT/'entries.json',entries)
    else:importer.prepare(rotations)
    entries=json.loads((OUT/'entries.json').read_text())
    for a in entries:
        if a['assetId']=='asset-gym-multi-gym-stl':
            a['description']+=' Unitless STL interpreted as millimetres; scale is provisional.'
            a['source']['unitInterpretation']=dict(sourceUnits='unspecified',assumedUnits='mm',scaleToMeters=.001,status='inferred')
        if a['assetId']=='asset-gym-dumbbell-rack':
            origin=json.loads((OUT/'original-sources.json').read_text())
            a['source']['archive']=dict(fileName='dumbbell-rack-2.snapshot.1.zip',sha256=origin['archiveSha256'],member=origin['archiveMember'])
        importer.write((ROOT/a['artifact']).parent/'catalog-entry.json',a)
    importer.write(OUT/'entries.json',entries)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','prepare','gpu'])
    parser.add_argument('--rotations',type=Path)
    args=parser.parse_args()
    convert() if args.phase=='convert' else prepare(args.rotations,args.phase=='gpu')
