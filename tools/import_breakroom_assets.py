"""Convert user-supplied breakroom STEP models and prepare library entries."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'.runtime/breakroom-import-20261003'
SOURCE=Path(r'C:/Users/might/Downloads/more break stuff')
LIBRARY=ROOT/'generated/industrial_assets/local_library'
CATEGORY='Building Elements'
DESCRIPTION='User-supplied kitchen appliance; CAD-derived dimensions, operational and installation requirements unverified.'
TAGS=('kitchen','breakroom','cafeteria','appliance')
NAME_PREFIX='breakroom-'
ITEMS=[('coffee-pot','Coffee Pot','CoffeePot_Assembly.stp'),
       ('refrigerator','Refrigerator','frigde.STEP'),
       ('microwave','Microwave Oven','MicrowaveOven.stp'),
       ('toaster','Toaster','toaster.stp')]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,indent=2),encoding='utf-8')


def convert():
    sys.path.insert(0,str(ROOT/'.runtime/model-import-20261002/dependencies'))
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.Message import Message_ProgressRange
    from OCP.RWGltf import RWGltf_CafWriter
    from OCP.RWMesh import RWMesh_CoordinateSystem_Yup
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TCollection import TCollection_AsciiString,TCollection_ExtendedString
    from OCP.TColStd import TColStd_IndexedDataMapOfStringString
    from OCP.TDF import TDF_LabelSequence
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFDoc import XCAFDoc_DocumentTool

    OUT.mkdir(parents=True,exist_ok=False)
    (OUT/'catalog-before.json').write_bytes((LIBRARY/'catalog.json').read_bytes())
    layouts=ROOT/'.runtime/facility-layout/layouts/local/site-local/layouts'
    write(OUT/'before-hashes.json',dict(catalog=sha(LIBRARY/'catalog.json'),
        sources={filename:sha(SOURCE/filename) for _,_,filename in ITEMS},
        layouts={p.name:sha(p) for p in layouts.glob('*.json')}))
    results=[]
    for slug,name,filename in ITEMS:
        start=time.monotonic();asset_id='asset-'+NAME_PREFIX+slug
        target=LIBRARY/(NAME_PREFIX+slug);target.mkdir(exist_ok=False)
        source=SOURCE/filename;shutil.copy2(source,target/filename)
        doc=TDocStd_Document(TCollection_ExtendedString('MDTV-XCAF'))
        reader=STEPCAFControl_Reader();reader.SetColorMode(True);reader.SetNameMode(True)
        assert reader.ReadFile(str(source))==IFSelect_RetDone
        assert reader.Transfer(doc)
        tool=XCAFDoc_DocumentTool.ShapeTool_s(doc.Main());labels=TDF_LabelSequence();tool.GetFreeShapes(labels)
        assert labels.Length()>0
        for index in range(1,labels.Length()+1):
            mesher=BRepMesh_IncrementalMesh(tool.GetShape_s(labels.Value(index)),.2,False,.25,True)
            assert mesher.IsDone()
        glb=target/'model.glb'
        writer=RWGltf_CafWriter(TCollection_AsciiString(str(glb)),True);writer.SetMergeFaces(True)
        converter=writer.ChangeCoordinateSystemConverter()
        converter.SetInputCoordinateSystem(RWMesh_CoordinateSystem_Yup)
        converter.SetOutputCoordinateSystem(RWMesh_CoordinateSystem_Yup)
        converter.SetInputLengthUnit(.001);converter.SetOutputLengthUnit(1)
        assert writer.Perform(doc,TColStd_IndexedDataMapOfStringString(),Message_ProgressRange())
        result=dict(assetId=asset_id,name=name,source=filename,sourceSha256=sha(source),
                    artifact=glb.relative_to(ROOT).as_posix(),bytes=glb.stat().st_size,
                    rootCount=labels.Length(),seconds=round(time.monotonic()-start,2))
        results.append(result);write(OUT/'conversion.json',results);print(json.dumps(result),flush=True)


def prepare(rotations):
    sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
    import publish_local_machine_library as publisher
    from functools import partial
    publisher.render_software_thumbnail=partial(publisher.render_software_thumbnail,maximum_triangles=1100000)
    publisher.SOFTWARE_THUMBNAIL_THRESHOLD_BYTES=0
    orientations=json.loads(rotations.read_text()) if rotations else {}
    entries=[]
    for result in json.loads((OUT/'conversion.json').read_text()):
        aid=result['assetId'];glb=ROOT/result['artifact'];target=glb.parent
        source=publisher.SourceAsset(aid,result['name'],CATEGORY,result['source'],'interchange',
            DESCRIPTION,TAGS,tuple(orientations.get(aid,[0,0,0])))
        entry=publisher._catalog_entry(source,SOURCE/result['source'],glb,target)
        assert entry['source']['sha256']==result['sourceSha256']
        display=target/'model-display.glb'
        if display.exists():
            entry['artifact']=display.relative_to(ROOT).as_posix()
            entry['visualImport']=json.loads((target/'display-mesh-evidence.json').read_text())
            entry['description']+=' Simplified display mesh; original STEP and full GLB retained.'
            publisher.render_software_thumbnail(display,target/'thumbnail.webp',
                evidence_path=target/'thumbnail-evidence.json',width=480,height=300,
                source_transform=publisher._rotation_matrix_xyz_degrees(source.canonical_rotation_degrees))
        publisher._write_json_atomic(target/'catalog-entry.json',entry)
        entries.append(entry);print(json.dumps(dict(assetId=aid,dimensions=entry['dimensions'])),flush=True)
    write(OUT/'entries.json',entries)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','prepare'])
    parser.add_argument('--rotations',type=Path)
    args=parser.parse_args()
    convert() if args.phase=='convert' else prepare(args.rotations)
