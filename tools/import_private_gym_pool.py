"""Import the owner's two pool concepts and corner jacuzzi without resizing CAD."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT=ROOT/'.runtime/private-gym-pool-import-20261008'
SOURCE=Path('C:/Users/might/Downloads')
ITEMS=[('concept-1','Swimming Pool Concept 1','pool.stp'),
       ('concept-2','Swimming Pool Concept 2','Swimming Pool v2.step'),
       ('jacuzzi','Corner Jacuzzi - 1500 mm','Jacuzzi Bathtub - 1500x1500mm Corner Bath.stp')]


def convert():
    OUT.mkdir(parents=True,exist_ok=True);items=[]
    for key,name,filename in ITEMS:
        target=base.LIBRARY/('gym-pool-'+key);target.mkdir(parents=True,exist_ok=True)
        source=SOURCE/filename
        if not (target/filename).exists():copy2(source,target/filename)
        assert base.sha(source)==base.sha(target/filename)
        item=dict(assetId='asset-gym-pool-'+key,displayName=name,source=filename,
                  sourceSha256=base.sha(source),format=source.suffix.lower(),target=target.relative_to(ROOT).as_posix())
        items.append(item);receipt=OUT/(item['assetId']+'-conversion.json')
        if receipt.exists():
            old=json.loads(receipt.read_text());assert old['sourceSha256']==item['sourceSha256']
            if old['status']=='converted':continue
        result=base.convert_interchange(item,True)
        result['emptyCompoundNodesRemoved']=remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted',assetId=item['assetId'],sourceSha256=item['sourceSha256'])
        base.write(receipt,result);print(json.dumps(result),flush=True)
    base.write(OUT/'inventory.json',items)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase',choices=['convert','prepare']);parser.add_argument('--review',type=Path)
    args=parser.parse_args()
    if args.phase=='convert':convert()
    else:
        base.OUT=OUT;base.prepare(args.review,set())
        for key,*_ in ITEMS:
            path=base.LIBRARY/('gym-pool-'+key)/'catalog-entry.json'
            entry=json.loads(path.read_text());entry['description']=('Owner-supplied pool/spa CAD at source scale. '
                'Geometry and units are measured; structural support, drainage, waterproofing, ventilation, '
                'water treatment, access and occupancy are not qualified.')
            entry['tags']=['gym','pool','spa',key];base.write(path,entry)
