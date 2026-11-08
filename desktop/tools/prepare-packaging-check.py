"""Create a disposable normal-desktop profile. No live documents or credentials.

--withhold reportlab|py3dbp copies the runtime folder and replaces that package with a stub that cannot be imported
(the native profile check requires each package folder, so this models a damaged install that is still present).
With --expect-missing, the native check verifies each listed component fails clearly when used: pdf_report and
arrangement need the matching --withhold, step_worker a --geometry-python without the OCP geometry component.
--remove PACKAGE copies the runtime folder without that package at all, and --unusable-step-python points the
profile at a STEP Python that does not exist: the native check verifies the application still starts, says why,
and has Packaging (or only STEP import) off. Each runs alone.
"""
import argparse
import json
from pathlib import Path
import shutil
import socket
import subprocess
from uuid import uuid4

WITHHELD = {'reportlab': 'pdf_report', 'py3dbp': 'arrangement'}
PACKAGES = ('py3dbp', 'trimesh', 'reportlab', 'numpy', 'PIL')
STUB = b'raise ImportError("TEST: component withheld for the native missing-component check")\n'

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--dependencies', type=Path, required=True)
    parser.add_argument('--geometry-python', type=Path, required=True)
    parser.add_argument('--step-source', type=Path, required=True)
    parser.add_argument('--ribbon-only', action='store_true', help='Verify ribbon presentation without creating documents')
    parser.add_argument('--facility-ribbon-only', action='store_true', help='Verify Facility ribbon using disposable geometry only')
    parser.add_argument('--withhold', action='append', choices=sorted(WITHHELD), default=[])
    parser.add_argument('--expect-missing', action='append', choices=['arrangement', 'pdf_report', 'step_worker'], default=[])
    parser.add_argument('--remove', choices=PACKAGES)
    parser.add_argument('--unusable-step-python', action='store_true')
    args = parser.parse_args()
    output = args.output.resolve()
    if not output.is_relative_to(ROOT / '.runtime'):
        raise ValueError('Test stores must be inside this worktree .runtime')
    if sum(map(bool, (args.withhold or args.expect_missing, args.remove, args.unusable_step_python))) > 1:
        raise ValueError('--remove and --unusable-step-python each run alone')
    if sorted(WITHHELD[name] for name in args.withhold) != sorted(set(args.expect_missing) - {'step_worker'}):
        raise ValueError('Each withheld package needs its --expect-missing component, and the reverse')
    if 'step_worker' in args.expect_missing and subprocess.run(
            [str(args.geometry_python), '-I', '-c', 'import importlib.util,sys; sys.exit(importlib.util.find_spec("OCP") is not None)'],
            capture_output=True, timeout=60, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0)).returncode:
        raise ValueError('step_worker expects a geometry Python without OCP')
    output.mkdir(parents=True, exist_ok=False)
    dependencies = args.dependencies.resolve()
    if args.withhold:
        copy = output / 'dependencies'
        shutil.copytree(dependencies, copy, ignore=lambda folder, names: [n for n in names if Path(folder) == dependencies and n in args.withhold])
        for name in args.withhold:
            (copy / name).mkdir()
            (copy / name / '__init__.py').write_bytes(STUB)
        dependencies = copy
    if args.remove:
        copy = output / 'dependencies'
        shutil.copytree(dependencies, copy, ignore=lambda folder, names: [n for n in names if Path(folder) == dependencies and n == args.remove])
        dependencies = copy
    geometry = output / 'missing-step-python' / 'python.exe' if args.unusable_step_python else args.geometry_python.resolve()
    stores = {name: str(output / name) for name in ('dataRoot', 'facilityRoot', 'libraryRoot')}
    for value in stores.values():
        Path(value).mkdir()
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    profile = dict(schemaVersion=1, mode='application', profileId='packaging-native-' + uuid4().hex[:8],
                   origin=f'http://127.0.0.1:{port}', backendId=str(uuid4()), storeId=str(uuid4()),
                   startupLayoutId=None, **stores,
                   packagingRuntime=dict(schemaVersion=1, dependencyRoot=str(dependencies), geometryPython=str(geometry)))
    (output / 'profile.json').write_text(json.dumps(profile, indent=2), encoding='utf-8')
    (Path(stores['dataRoot']) / 'packaging-check.json').write_text(json.dumps({
        'disposable': True, 'stepSource': str(args.step_source.resolve()), 'store': stores['dataRoot'],
        'ribbonOnly': args.ribbon_only,
        'facilityRibbonOnly': args.facility_ribbon_only,
        'expectMissing': sorted(set(args.expect_missing)),
        'expectUnavailable': 'package:' + args.remove if args.remove else 'step-python' if args.unusable_step_python else None,
    }), encoding='utf-8')
    print(output / 'profile.json')


if __name__ == '__main__':
    main()
