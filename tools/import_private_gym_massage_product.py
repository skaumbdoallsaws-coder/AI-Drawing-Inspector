"""Import the owner's STEP massage chair without changing source geometry."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT=ROOT/'.runtime/private-gym-massage-product-20261011'
SOURCE=Path('C:/Users/might/OneDrive/Desktop/additional parts/Massage-Product-Chair.stp')
ASSET='asset-gym-massage-product-chair'
TARGET=base.LIBRARY/'gym-massage-product-chair'


def convert():
    OUT.mkdir(parents=True,exist_ok=True);TARGET.mkdir(parents=True,exist_ok=True)
    destination=TARGET/SOURCE.name
    if not destination.exists():copy2(SOURCE,destination)
    assert base.sha(SOURCE)==base.sha(destination)
    item=dict(assetId=ASSET,displayName='Massage Product Chair',source=SOURCE.name,
        sourceSha256=base.sha(SOURCE),format='.stp',target=TARGET.relative_to(ROOT).as_posix())
    receipt=OUT/(ASSET+'-conversion.json')
    if receipt.exists():
        result=json.loads(receipt.read_bytes())
        assert result['sourceSha256']==item['sourceSha256'] and result['status']=='converted'
    else:
        result=base.convert_interchange(item,True)
        result['emptyCompoundNodesRemoved']=remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted',assetId=ASSET,sourceSha256=item['sourceSha256'])
        base.write(receipt,result)
    base.write(OUT/'inventory.json',[item])
    print(json.dumps(result),flush=True)


def prepare():
    base.OUT=OUT
    base.prepare(OUT/'orientation.json',{ASSET})
    path=TARGET/'catalog-entry.json'
    entry=json.loads(path.read_bytes())
    entry.update(category='Facilities',tags=['gym','recovery','massage','chair'],
        description='Owner-supplied STEP massage chair at CAD-derived scale. Static imported pose only; powered motion, reclining envelope, installation and operating clearances unverified.')
    base.write(path,entry)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','prepare'])
    args=parser.parse_args()
    convert() if args.phase=='convert' else prepare()
