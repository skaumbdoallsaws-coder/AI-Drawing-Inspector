"""Copy manual layout and its authorities for normal-mode testing, never Save."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import uuid
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.runtime.application_profile import load_application_profile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8482)
    parser.add_argument('--include-documents', action='store_true')
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists() or ROOT not in destination.parents: raise ValueError('Use a fresh directory within the project')
    source = ROOT / '.runtime/facility-layout'
    layout_id = 'fl-reference-manual-20260812'
    relative = Path('layouts/local/site-local/layouts')
    source_file = source / relative / (layout_id + '.json')
    original = source_file.read_bytes()
    registry = json.loads((source / relative / 'registry.json').read_text(encoding='utf-8'))
    registry['layouts'] = [r for r in registry['layouts'] if r['layoutId'] == layout_id]
    registry['defaultLayoutId'] = layout_id
    target = destination / 'facility' / relative
    target.mkdir(parents=True)
    (target / source_file.name).write_bytes(original)
    (target / 'registry.json').write_text(json.dumps(registry, sort_keys=True, separators=(',', ':')), encoding='utf-8')
    native = lambda p: Path('\\\\?\\' + str(p)) if os.name == 'nt' else p
    shutil.copytree(native(source / 'authorities'), native(destination / 'facility/authorities'))
    if args.include_documents:
        documents = []
        for folder, target_name in [('parts_manual', 'parts-manual'), ('operations_manual', 'operations-manual'),
                                    ('specification_sheets', 'specification-sheets'), ('work_instructions', 'work-instructions')]:
            source_dir = ROOT / 'generated' / folder / 'mmle-50d'
            target_dir = destination / target_name / 'mmle-50d'
            shutil.copytree(native(source_dir), native(target_dir))
            for file in source_dir.rglob('*'):
                if file.is_file():
                    documents.append({'path': str(file), 'sha256': hashlib.sha256(file.read_bytes()).hexdigest()})
        (destination / 'workflow-documents-source.json').write_text(json.dumps(documents), encoding='utf-8')
    value = {'schemaVersion': 1, 'mode': 'application', 'profileId': 'application-check',
             'origin': f'http://127.0.0.1:{args.port}', 'dataRoot': str(destination),
             'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4()),
             'facilityRoot': str(destination / 'facility'), 'libraryRoot': str(ROOT / '400S_Sorted_Library'),
             'startupLayoutId': layout_id}
    profile = destination / 'profile.json'
    profile.write_text(json.dumps(value, indent=2), encoding='utf-8')
    (destination / 'application-check-source.json').write_text(json.dumps({'originalPath': str(source_file),
        'originalSha256': hashlib.sha256(original).hexdigest(), 'isolatedFacilityRoot': value['facilityRoot']}, indent=2), encoding='utf-8')
    load_application_profile(profile)
    print(json.dumps({'profile': str(profile), 'originalSha256': hashlib.sha256(original).hexdigest()}))


if __name__ == '__main__': main()
