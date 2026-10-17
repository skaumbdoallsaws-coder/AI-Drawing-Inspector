"""Launch a read-only Private Gym camera rehearsal, without provider calls."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
RELATIVE = Path('layouts/local/site-local/layouts/fl-private-gym-20261007.json')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--name', required=True)
    parser.add_argument('--fast', action='store_true')
    parser.add_argument('--overviews-only', action='store_true')
    parser.add_argument('--connected', action='store_true')
    parser.add_argument('--preflight-only', action='store_true')
    parser.add_argument('--pause-check', action='store_true')
    parser.add_argument('--intro-only', action='store_true')
    parser.add_argument('--artwork-check', action='store_true')
    args = parser.parse_args()
    if args.artwork_check and not args.connected:
        parser.error('--artwork-check requires --connected')
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-_' for c in args.name):
        parser.error('Use lowercase letters, digits, dashes or underscores for name')
    out = ROOT / '.runtime/private-gym-tour' / args.name
    out.mkdir(parents=True, exist_ok=False)
    (out / 'runtime').mkdir()
    live = ROOT / '.runtime/facility-layout'
    before = (live / RELATIVE).read_bytes()
    native = lambda value: '\\\\?\\' + str(value.resolve())
    for folder in ('authorities', 'layouts'):
        shutil.copytree(native(live / folder), native(out / 'store' / folder))
    assert (out / 'store' / RELATIVE).read_bytes() == before
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    profile = dict(schemaVersion=1, mode='application', profileId='private-gym-tour',
                   origin=f'http://127.0.0.1:{port}', dataRoot=str(out / 'runtime'),
                   facilityRoot=str(out / 'store'), libraryRoot=str(ROOT / '400S_Sorted_Library'),
                   backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()),
                   startupLayoutId='fl-private-gym-20261007')
    profile_file = out / 'profile.json'
    profile_file.write_text(json.dumps(profile, indent=2), encoding='utf-8')
    (out / 'tour.json').write_text(json.dumps(dict(fast=args.fast, overviewsOnly=args.overviews_only,
        preflightOnly=args.preflight_only, pauseCheck=args.pause_check, introOnly=args.intro_only,
        artworkCheck=args.artwork_check,
        originalHash=hashlib.sha256(before).hexdigest())), encoding='utf-8')
    if args.connected:
        sys.path.insert(0, str(ROOT))
        from ai_inspector.facility_layout.host import build_private_local_asset_catalog
        (out / 'catalog.json').write_text(json.dumps(build_private_local_asset_catalog(ROOT)), encoding='utf-8')
    env = dict(os.environ)
    for key in ('ELECTRON_RUN_AS_NODE', 'INSPECTORPRO_LLM_GATEWAY_CONFIG'):
        env.pop(key, None)
    electron = ROOT / 'desktop/node_modules/electron/dist/electron.exe'
    if not electron.exists():
        electron = Path.home() / 'Documents/Codex/2026-09-12/hi/work/inspectorpro-desktop/desktop/node_modules/electron/dist/electron.exe'
    with (out / 'stdout.log').open('wb') as stdout, (out / 'stderr.log').open('wb') as stderr:
        driver = 'connected.cjs' if args.connected else 'tour.cjs'
        child = subprocess.Popen([str(electron), str(Path(__file__).with_name(driver)),
            '--application', '--profile-file', str(profile_file), '--python',
            str(Path(sys.executable).with_name('python.exe'))], cwd=ROOT, env=env,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW)
        (out / 'launch.json').write_text(json.dumps(dict(pid=child.pid, status='running')))
        try:
            code = child.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
            code = child.wait(timeout=15)
        result = dict(code=code, savedUnchanged=(live / RELATIVE).read_bytes() == before)
        (out / 'launch.json').write_text(json.dumps(result, indent=2))
        print(json.dumps(result))


if __name__ == '__main__':
    main()
