"""Import the supplied soccer and outdoor-training models without rescaling CAD."""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT = ROOT / '.runtime/private-gym-fields-20261008'
SOURCE = Path('C:/Users/might/Videos')
ITEMS = [
    ('goal', 'Floorball Training Goal', 'indoor soccer', 'Floorball goal.STEP'),
    ('football', 'Football', 'indoor soccer', 'football - complete.stp'),
    ('pickup', 'Ford F-150 Pickup', 'open area', 'Ford_f150.stp'),
    ('bike', 'Outdoor Conditioning Exercise Bike', 'open area', 'heimtrainer.stp'),
    ('rear-wheel', 'Rear Wheel', 'open area', 'Rear Wheel.SLDPRT'),
    ('tire', 'Training Tire', 'open area', 'Tyre.SLDPRT'),
    ('wall-rack', 'Wall-Mounted Training Rack', 'open area', 'Wall Mount Rack.stp'),
]


def convert():
    OUT.mkdir(parents=True, exist_ok=True)
    items = []
    assert base.sha(SOURCE/'open area/Tyre.SLDPRT') == base.sha(SOURCE/'open area/Tyre (1).SLDPRT')
    for key, name, folder, filename in ITEMS:
        target = base.LIBRARY / ('gym-field-' + key)
        target.mkdir(parents=True, exist_ok=True)
        source = SOURCE / folder / filename
        if not (target / filename).exists():
            shutil.copy2(source, target / filename)
        assert base.sha(source) == base.sha(target / filename)
        item = dict(assetId='asset-gym-field-' + key, displayName=name, source=filename,
                    sourceSha256=base.sha(source), format=source.suffix.lower(),
                    target=target.relative_to(ROOT).as_posix())
        items.append(item)
        receipt = OUT / (item['assetId'] + '-conversion.json')
        if receipt.exists():
            assert json.loads(receipt.read_text())['sourceSha256'] == item['sourceSha256']
            continue
        print('Converting ' + name, flush=True)
        if item['format'] == '.sldprt':
            exporter = ROOT / '.runtime/additional-gym-import-20261004/bin/AdditionalGymPartExporter.exe'
            with (target/'extractor.log').open('w') as log:
                process = subprocess.run([str(exporter), str(target/filename), str(target)],
                    stdout=log, stderr=subprocess.STDOUT, timeout=300,
                    creationflags=subprocess.CREATE_NO_WINDOW)
            assert process.returncode == 0, (name, (target/'extractor.log').read_text())
            evidence = json.loads((target/'native-export.json').read_text(encoding='utf-8-sig'))
            bodies = json.loads((target/'model_process_bodies.json').read_text(encoding='utf-8-sig'))['bodies']
            assert len(bodies) == evidence['visibleBodies']
            assert sum(b['faceCount'] for b in bodies) == evidence['visibleFaces']
            result = dict(artifact=(target/'model_body.glb').relative_to(ROOT).as_posix(),
                nativeEvidence=evidence, units=dict(sourceUnits='m', authority='SolidWorks_API_meters'))
        else:
            result = base.convert_interchange(item)
            result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT/result['artifact'])
        result.update(status='converted', assetId=item['assetId'], sourceSha256=item['sourceSha256'])
        base.write(receipt, result)
        print(json.dumps(dict(assetId=item['assetId'], status='converted')), flush=True)
    base.write(OUT/'inventory.json', items)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'prepare'])
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    if args.phase == 'convert':
        convert()
    else:
        base.OUT = OUT
        base.prepare(args.review, set())
