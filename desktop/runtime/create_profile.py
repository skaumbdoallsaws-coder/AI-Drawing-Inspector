"""Create one explicit isolated developer profile; never migrate an existing store."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import argparse
import json
import uuid
from desktop.runtime.profile import local_path, prepare_profile, write_exclusive


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-file', type=Path, required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--profile-id', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--acceptance-layout-id')
    args = parser.parse_args()
    target = local_path(args.profile_file)
    if target.exists(): raise ValueError('Profile file already exists; explicit profiles are never overwritten')
    value = {'schemaVersion': 1, 'mode': 'managed', 'profileId': args.profile_id,
             'origin': 'http://127.0.0.1:' + str(args.port), 'dataRoot': str(local_path(args.data_root)),
             'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4()), 'acceptanceLayoutId': args.acceptance_layout_id}
    profile = prepare_profile(value, ROOT)
    write_exclusive(target, value)
    print(json.dumps({'profileFile': str(target), 'profileId': value['profileId'], 'storeBinding': profile.marker['storeBinding']}))


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(str(error), file=sys.stderr); raise SystemExit(1)
