"""Create an explicit normal desktop profile; never copy or save a layout."""
import argparse
import json
from pathlib import Path
import sys
import uuid
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from desktop.runtime.application_profile import load_application_profile


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--data-root', type=Path, required=True)
    p.add_argument('--facility-root', type=Path, required=True)
    p.add_argument('--library-root', type=Path, required=True)
    p.add_argument('--port', type=int, default=8480)
    p.add_argument('--profile-id', default='inspectorpro-application')
    p.add_argument('--layout-id', default='fl-reference-manual-20260812')
    args = p.parse_args()
    if args.output.exists(): raise ValueError('An existing profile will not be replaced')
    for path in [args.output, args.data_root, args.facility_root, args.library_root]:
        if not path.is_absolute(): raise ValueError('Absolute local paths are required')
    if not args.facility_root.is_dir() or not args.library_root.is_dir(): raise ValueError('Selected stores must already exist')
    args.data_root.mkdir(parents=True, exist_ok=True)
    value = {'schemaVersion': 1, 'mode': 'application', 'profileId': args.profile_id, 'origin': f'http://127.0.0.1:{args.port}',
             'dataRoot': str(args.data_root.resolve()), 'facilityRoot': str(args.facility_root.resolve()),
             'libraryRoot': str(args.library_root.resolve()), 'startupLayoutId': args.layout_id,
             'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4())}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as f: json.dump(value, f, indent=2)
    load_application_profile(args.output)
    print(json.dumps({'profile': str(args.output), 'mode': 'application', 'origin': value['origin']}))


if __name__ == '__main__': main()
