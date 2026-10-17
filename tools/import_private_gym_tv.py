"""Measure and stage the supplied TV unit without changing existing library entries."""
import argparse
import json
from pathlib import Path
from shutil import copy2
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'tools')]
from tools import import_additional_gym_assets as base
from tools.import_private_gym_sports import remove_empty_cad_nodes

OUT = ROOT / '.runtime/private-gym-tv-20261010'
SOURCE = Path('C:/Users/might/Downloads/TV UNIT ASSEMBLY.STEP')
ASSET = 'asset-gym-lounge-tv-unit'
TARGET = base.LIBRARY / 'gym-lounge-tv-unit'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('phase', choices=['convert', 'prepare', 'publish'])
    parser.add_argument('--review', type=Path)
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    if args.phase == 'convert':
        TARGET.mkdir(parents=True, exist_ok=True)
        if not (TARGET / SOURCE.name).exists():
            copy2(SOURCE, TARGET / SOURCE.name)
        digest = base.sha(SOURCE)
        assert base.sha(TARGET / SOURCE.name) == digest
        item = dict(assetId=ASSET, displayName='Lounge TV Unit Assembly', source=SOURCE.name,
                    sourceSha256=digest, format='.step', target=TARGET.relative_to(ROOT).as_posix())
        receipt = OUT / (ASSET + '-conversion.json')
        if receipt.exists():
            result = json.loads(receipt.read_text())
            assert result['sourceSha256'] == digest and result['status'] == 'converted'
        else:
            result = base.convert_interchange(item, retry_failed_faces=True)
            result['emptyCompoundNodesRemoved'] = remove_empty_cad_nodes(ROOT / result['artifact'])
            result.update(status='converted', assetId=ASSET, sourceSha256=digest)
            base.write(receipt, result)
        base.write(OUT / 'inventory.json', [item])
        print(json.dumps(result))
    elif args.phase == 'prepare':
        base.OUT = OUT
        base.prepare(args.review, {ASSET})
        path = TARGET / 'catalog-entry.json'
        entry = json.loads(path.read_text())
        entry['displayName'] = 'Lounge TV Console Cabinet'
        entry['description'] = 'User-supplied TV unit assembly, measured from STEP geometry in metres. Installation and electrical requirements are unverified.'
        entry['tags'] = ['television', 'TV', 'lounge', 'furniture']
        base.write(path, entry)
    else:
        path = base.LIBRARY / 'catalog.json'
        original = path.read_bytes()
        library = json.loads(original)
        entry = json.loads((TARGET / 'catalog-entry.json').read_text())
        existing = next((a for a in library['assets'] if a['assetId'] == ASSET), None)
        if existing:
            assert existing == entry, 'A different TV entry is already published'
            return
        assert (OUT / 'asset-visual-review.json').exists(), 'Review the converted model before publication'
        review = json.loads((OUT / 'asset-visual-review.json').read_text())
        assert review['status'] == 'passed' and review['artifactSha256'] == base.sha(ROOT / entry['artifact'])
        backup = OUT / 'catalog-before.json'
        if backup.exists():
            assert backup.read_bytes() == original, 'Library changed; review before publishing'
        else:
            backup.write_bytes(original)
        library['assets'].append(entry)
        library['summary']['total'] = len(library['assets'])
        assert path.read_bytes() == original
        base.write(path, library)
        print(json.dumps(dict(status='published', assetId=ASSET, dimensions=entry['dimensions'])))


if __name__ == '__main__':
    main()
