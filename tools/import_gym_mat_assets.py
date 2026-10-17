"""Import the gym-mat download batch using the existing reviewed CAD pipeline."""
import argparse
from collections import Counter
import importlib.util
import json
from pathlib import Path
import shutil
import struct
import sys

import import_additional_gym_assets as common

ROOT = common.ROOT
OUT = ROOT / '.runtime/gym-mat-import-20261007'
SOURCE = Path('C:/Users/might/Downloads/gym mat')
PREVIOUS = ROOT / '.runtime/additional-gym-import-20261004'
LIBRARY = common.LIBRARY
ITEMS = [
    ('assembly-asm1', 'Exercise Assembly Asm1', 'Asm1.stp'),
    ('mid-row', 'Techno Gym Mid Row', 'Assem Techno Gym Mid Row.STEP'),
    ('booty-blaster', 'Booty Blaster Trainer', 'Booty Blaster Trainer.stp'),
    ('elliptical', 'Elliptical Machine', 'elliptical machine.STEP'),
    ('exercise-machine', 'Exercise Machine', 'Exercise Machine.step'),
    ('incline-lever-row', 'Incline Lever Row', 'FGYM001 - (CE001) - INCLINE LEVER ROW CON PESO.stp'),
    ('inter-v4', 'Exercise Component Inter V4', 'inter v4.STEP'),
    ('mach1', 'Exercise Machine Mach1', 'mach1.STEP'),
    ('model', 'Exercise Equipment Model', 'model.STEP'),
    ('multi-gym', 'Multi Gym', 'Multi_Gym.stp'),
    ('pool-table', 'Pool Table', 'Pool Table v21.step'),
    ('power-tower', 'Power Tower Fitness Station', 'Power tower fitness.IGS'),
    ('product1', 'Exercise Assembly Product1', 'Product1.CATProduct.stp'),
    ('scott-bench', 'Scott Curl Bench', 'SCOTT BENCH ASSEMBLY_29032017_0334 stp.STEP'),
    ('seated-calf', 'Seated Calf Raise Machine', 'Seated Calf Raise Machine.STEP'),
    ('smith-machine', 'Smith Machine', 'Smith Machine v84.step'),
    ('stationary-bike', 'Stationary Bike', 'stationary bike.STEP'),
    ('stl-equipment', 'Exercise Equipment STL - Scale Review', 'step file.stl'),
    ('triceps', 'Triceps Machine', 'TRICEPSC.step'),
    ('workout-bench', 'Workout Bench', 'Workout Bench.STEP'),
    ('weight-rack', 'Weight Rack', 'WRACKSC.stp'),
    ('native-multi-gym', 'Multi Gym Assembly', 'another gym equip assembly/GYM.SLDASM'),
]
common.OUT, common.SOURCE = OUT, SOURCE


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def load_helper(name, file):
    spec = importlib.util.spec_from_file_location(name, file)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.OUT = OUT
    return module


def source_hashes():
    return {p.relative_to(SOURCE).as_posix(): common.sha(p) for p in SOURCE.rglob('*') if p.is_file()}


def native_receipt():
    item = next(i for i in read(OUT / 'inventory.json') if i['format'] == '.sldasm')
    target = ROOT / item['target']
    audit = read(target / 'native-export.json')
    assert not audit['missing'] and not audit['suppressed'] and audit['errors'] == 0
    glb = target / 'model_colored.glb'
    with glb.open('rb') as stream:
        stream.seek(12)
        size, kind = struct.unpack('<II', stream.read(8))
        assert kind == 0x4E4F534A
        document = json.loads(stream.read(size))
    # The existing native exporter serializes its node labels as ASCII.
    expected = Counter(n.encode('ascii', errors='replace').decode('ascii') for n in audit['partInstances'])
    actual = Counter(n['name'] for n in document['nodes'] if 'mesh' in n)
    assert expected == actual, (expected - actual, actual - expected)
    assert all(p.get('mode', 4) == 4 and document['accessors'][p['indices']]['count'] > 0
               for m in document['meshes'] for p in m['primitives'])
    assert common.sha(target / item['source']) == item['sourceSha256']
    common.write(OUT / (item['assetId'] + '-conversion.json'), dict(
        assetId=item['assetId'], sourceSha256=item['sourceSha256'], status='converted',
        artifact=glb.relative_to(ROOT).as_posix(), bytes=glb.stat().st_size,
        nativeEvidence=audit, verifiedPartInstances=sum(actual.values()),
        units=dict(sourceUnits='m', authority='SolidWorks_API_meters')))


def repair_empty_compounds(selected):
    for item in read(OUT / 'inventory.json'):
        aid = item['assetId']
        receipt = OUT / (aid + '-conversion.json')
        if (selected and aid not in selected) or not receipt.exists():
            continue
        result = read(receipt)
        if result['status'] != 'converted':
            continue
        source = ROOT / result['artifact']
        data = source.read_bytes()
        size, kind = struct.unpack_from('<II', data, 12)
        assert kind == 0x4E4F534A
        document = json.loads(data[20:20+size])
        meshes, remap, removed = [], {}, []
        for index, mesh in enumerate(document['meshes']):
            keep = []
            for primitive in mesh['primitives']:
                position = primitive['attributes'].get('POSITION')
                if position == -1 and primitive.get('indices') == -1:
                    assert primitive['attributes'] == {'POSITION': -1}
                    removed.append(dict(mesh=index, name=mesh.get('name'), reason='Empty CAD compound: no vertex or index accessor'))
                else:
                    assert isinstance(position, int) and position >= 0
                    assert document['accessors'][position]['type'] == 'VEC3'
                    keep.append(primitive)
            if keep:
                remap[index] = len(meshes)
                meshes.append(dict(mesh, primitives=keep))
        if not removed:
            continue
        assert meshes and result['sourceFaces'] == result['meshedFaces'] + len(result.get('negligibleFaces', []))
        document['meshes'] = meshes
        for node in document['nodes']:
            if 'mesh' in node:
                original = node.pop('mesh')
                if original in remap:
                    node['mesh'] = remap[original]
        encoded = json.dumps(document, separators=(',', ':')).encode('utf-8')
        encoded += b' ' * (-len(encoded) % 4)
        tail = data[20+size:]
        output = source.with_name('model-valid.glb')
        output.write_bytes(struct.pack('<III', 0x46546C67, 2, 20+len(encoded)+len(tail))
                           + struct.pack('<II', len(encoded), kind) + encoded + tail)
        result.update(originalArtifact=result['artifact'], originalArtifactSha256=common.sha(source),
                      artifact=output.relative_to(ROOT).as_posix(), bytes=output.stat().st_size,
                      emptyCompoundRepair=dict(removed=removed, binaryGeometryUnchanged=True))
        common.write(receipt, result)


def contact():
    from PIL import Image, ImageDraw, ImageFont
    available = [i for i in read(OUT / 'inventory.json')
                 if (ROOT / i['target'] / 'thumbnail.webp').exists()]
    width, height, columns = 400, 300, 4
    result = Image.new('RGB', (width*columns, height*((len(available)+columns-1)//columns)), 'white')
    draw = ImageDraw.Draw(result)
    font = ImageFont.truetype('C:/Windows/Fonts/arial.ttf', 15)
    for index, item in enumerate(available):
        x, y = (index % columns)*width, (index//columns)*height
        folder = ROOT / item['target']
        with Image.open(folder / 'thumbnail.webp') as preview:
            preview = preview.convert('RGB')
            preview.thumbnail((width, 240))
            result.paste(preview, (x, y))
        entry = read(folder / 'catalog-entry.json')
        draw.text((x+8, y+242), item['assetId'].removeprefix('asset-gym-commercial-'), fill='black', font=font)
        d = entry['dimensions']
        draw.text((x+8, y+264), f"W {d['width']:.2f} H {d['height']:.2f} D {d['depth']:.2f} m", fill='black', font=font)
    result.save(OUT / 'review-contact.jpg', quality=93)
    print(len(available))


def inventory():
    OUT.mkdir(parents=True, exist_ok=False)
    sources = source_hashes()
    catalog = read(LIBRARY / 'catalog.json')
    seen = {e.get('source', {}).get('sha256'): e['assetId'] for e in catalog['assets']}
    items, duplicates = [], []
    for slug, name, filename in ITEMS:
        aid = 'asset-gym-commercial-' + slug
        digest = sources[filename]
        if digest in seen:
            duplicates.append(dict(file=filename, duplicateOf=seen[digest]))
            continue
        seen[digest] = aid
        target = LIBRARY / aid.removeprefix('asset-')
        target.mkdir(exist_ok=False)
        if Path(filename).suffix.lower() == '.sldasm':
            for p in (SOURCE / filename).parent.iterdir():
                if p.is_file() and not p.name.startswith('~$'):
                    shutil.copy2(p, target / p.name)
        else:
            shutil.copy2(SOURCE / filename, target / Path(filename).name)
        items.append(dict(assetId=aid, displayName=name, source=Path(filename).name,
            sourceRelativePath=filename, sourceSha256=digest, format=Path(filename).suffix.lower(),
            target=target.relative_to(ROOT).as_posix()))
    common.write(OUT / 'inventory.json', items)
    common.write(OUT / 'before.json', dict(sources=sources, layouts=common.layout_hashes(),
        catalogSha256=common.sha(LIBRARY / 'catalog.json'), duplicates=duplicates))
    shutil.copy2(LIBRARY / 'catalog.json', OUT / 'catalog-before.json')
    common.write(OUT / 'review.json', {'asset-gym-commercial-stl-equipment': {
        'publish': False, 'note': 'Unitless STL requires dimensional confirmation before placement.'}})
    print(json.dumps(dict(candidates=len(items), duplicates=duplicates)), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['inventory', 'convert', 'native-receipt', 'pack', 'prepare', 'gpu', 'contact'])
    parser.add_argument('--asset', action='append', default=[])
    args = parser.parse_args()
    selected = set(args.asset)
    if args.phase == 'inventory':
        inventory()
    elif args.phase == 'native-receipt':
        native_receipt()
    elif args.phase == 'convert':
        chosen = {i['assetId'] for i in read(OUT / 'inventory.json')
                  if i['format'] != '.sldasm' and (not selected or i['assetId'] in selected)}
        common.convert('interchange', chosen)
        assert all(read(OUT / (a + '-conversion.json'))['status'] == 'converted' for a in chosen)
    elif args.phase == 'pack':
        repair_empty_compounds(selected)
        helper = load_helper('gym_mat_review', PREVIOUS / 'review_models.py')
        helper.pack(selected)
    elif args.phase == 'contact':
        contact()
    else:
        if args.phase == 'gpu':
            import publish_local_machine_library as publisher
            from render_streamed_asset_thumbnail import render_streamed_asset_thumbnail
            publisher.render_industrial_asset_thumbnail = render_streamed_asset_thumbnail
        common.prepare(OUT / 'review.json', selected, args.phase == 'gpu')


if __name__ == '__main__':
    main()
