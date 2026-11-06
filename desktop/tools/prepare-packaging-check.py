"""Create a disposable normal-desktop profile. No live documents or credentials."""
import argparse
import json
from pathlib import Path
import socket
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path, required=True)
    parser.add_argument('--geometry-python', type=Path, required=True)
    parser.add_argument('--step-source', type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / '.runtime'):
        raise ValueError('Test stores must be inside this worktree .runtime')
    output.mkdir(parents=True, exist_ok=False)
    stores = {name: str(output / name) for name in ('dataRoot', 'facilityRoot', 'libraryRoot')}
    for value in stores.values():
        Path(value).mkdir()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    profile = dict(schemaVersion=1, mode='application', profileId='packaging-native-' + uuid4().hex[:8],
                   origin=f'http://127.0.0.1:{port}', backendId=str(uuid4()), storeId=str(uuid4()),
                   startupLayoutId=None, **stores,
                   packagingRuntime=dict(schemaVersion=1, dependencyRoot=str(args.dependencies.resolve()),
                                         geometryPython=str(args.geometry_python.resolve())))
    (output / 'profile.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')
    (Path(stores['dataRoot']) / 'packaging-check.json').write_text(json.dumps({
        'disposable': True, 'stepSource': str(args.step_source.resolve()), 'store': stores['dataRoot'],
    }), encoding='utf-8')
    print(output / 'profile.json')


if __name__ == '__main__':
    main()
