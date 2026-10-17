"""Import the two supplied bookshelf concepts, retaining their modeled books."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from tools import import_additional_gym_assets as base

OUT = ROOT / '.runtime/private-gym-bookshelves-20261010'
SOURCE = Path('C:/Users/might/OneDrive/Desktop/additional parts')
ITEMS = [('floor', 'Floor Bookshelf with Books', 'Bookshelf floor.stl'),
         ('wall', 'Wall Bookshelf with Books', 'Bookshelf.stl')]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'prepare', 'publish'])
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.phase == 'convert':
        inventory = []
        for key, name, filename in ITEMS:
            target = base.LIBRARY / ('gym-office-bookshelf-' + key + '-books')
            target.mkdir(parents=True, exist_ok=True)
            if not (target / filename).exists():
                copy2(SOURCE / filename, target / filename)
            digest = base.sha(SOURCE / filename)
            assert base.sha(target / filename) == digest
            item = dict(assetId='asset-gym-office-bookshelf-' + key + '-books', displayName=name,
                        source=filename, sourceSha256=digest, format='.stl', target=target.relative_to(ROOT).as_posix())
            inventory.append(item)
            receipt = OUT / (item['assetId'] + '-conversion.json')
            if receipt.exists():
                previous = json.loads(receipt.read_text())
                assert previous['status'] == 'converted' and previous['sourceSha256'] == digest
            else:
                result = base.convert_stl(item)
                result.update(status='converted', assetId=item['assetId'], sourceSha256=digest)
                base.write(receipt, result)
        base.write(OUT / 'inventory.json', inventory)
        base.write(OUT / 'orientation.json', {i['assetId']: dict(rotation=[-90, 0, 0],
                   note='Source Z is vertical. Modeled books retained. STL has no unit metadata; centimetres are a provisional concept interpretation.') for i in inventory})
    elif args.phase == 'prepare':
        base.OUT = OUT
        base.prepare(OUT / 'orientation.json', set())
        for item in json.loads((OUT / 'inventory.json').read_text()):
            path = ROOT / item['target'] / 'catalog-entry.json'
            entry = json.loads(path.read_text())
            entry['category'] = 'Office & IT'
            entry['description'] = 'Owner-supplied bookshelf concept with all modeled books retained. Unitless STL interpreted as centimetres; dimensions are provisional, not installation or load-rating evidence.'
            entry['tags'] = ['office', 'bookshelf', 'books', 'furniture', 'concept scale']
            base.write(path, entry)
    else:
        proof = json.loads((OUT / 'asset-visual-review.json').read_text())
        assert proof['status'] == 'passed'
        manifest = base.LIBRARY / 'catalog.json'
        original = manifest.read_bytes()
        catalog = json.loads(original)
        additions = []
        for item in json.loads((OUT / 'inventory.json').read_text()):
            entry = json.loads((ROOT / item['target'] / 'catalog-entry.json').read_text())
            assert base.sha(ROOT / entry['artifact']) == proof['artifactHashes'][entry['assetId']]
            existing = next((a for a in catalog['assets'] if a['assetId'] == entry['assetId']), None)
            if existing:
                assert existing == entry, 'Published bookshelf entry changed'
            else:
                additions.append(entry)
        if not additions:
            return
        backup = OUT / 'catalog-before.json'
        if backup.exists():
            assert backup.read_bytes() == original, 'Library changed since review'
        else:
            backup.write_bytes(original)
        catalog['assets'].extend(additions)
        catalog['summary']['total'] = len(catalog['assets'])
        assert manifest.read_bytes() == original
        base.write(manifest, catalog)
        print(json.dumps(dict(status='published', assets=[a['assetId'] for a in additions])))


if __name__ == '__main__':
    main()
