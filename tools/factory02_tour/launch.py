"""Run a read-only Factory 02 rehearsal in an isolated native application."""
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
LAYOUT = 'layouts/local/site-local/layouts/fl-independent-factory-20260928.json'


def parse_args(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--name', required=True)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument('--full', action='store_true')
    scope.add_argument('--plan-only', action='store_true')
    scope.add_argument('--verify-ready', action='store_true', help='Check maximized, paused startup without running the tour')
    cue = parser.add_mutually_exclusive_group()
    cue.add_argument('--wait-for-cue', dest='wait_for_cue', action='store_true', default=True)
    cue.add_argument('--auto-start', dest='wait_for_cue', action='store_false', help='Start a rehearsal without a recording cue')
    parser.add_argument('--recording', action='store_true', help='Skip injected rehearsal pause and focus-loss checks')
    args = parser.parse_args(argv)
    if not args.name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.name):
        parser.error('name must contain only letters, numbers, hyphens, or underscores')
    if args.verify_ready and not args.wait_for_cue:
        parser.error('--verify-ready requires waiting for a cue')
    return args


def main(argv=None):
    args = parse_args(argv)
    out = ROOT / '.runtime/factory02-tour' / args.name
    out.mkdir(parents=True, exist_ok=False)
    (out / 'runtime').mkdir()
    live = ROOT / '.runtime/facility-layout'
    original = (live / LAYOUT).read_bytes()
    native = lambda p: '\\\\?\\' + str(p.resolve())
    for folder in ('authorities', 'layouts'):
        shutil.copytree(native(live / folder), native(out / 'store' / folder))
    if (out / 'store' / LAYOUT).read_bytes() != original:
        raise RuntimeError('Layout changed while snapshotting; retry with a stable saved layout')
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    profile = dict(schemaVersion=1, mode='application', profileId='factory02-tour',
                   origin=f'http://127.0.0.1:{port}', dataRoot=str(out / 'runtime'),
                   backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()),
                   facilityRoot=str(out / 'store'), libraryRoot=str(ROOT / '400S_Sorted_Library'),
                   startupLayoutId='fl-independent-factory-20260928')
    profile_file = out / 'profile.json'
    profile_file.write_text(json.dumps(profile, indent=2))
    (out / 'tour.json').write_text(json.dumps(dict(full=args.full, planOnly=args.plan_only,
        verifyReady=args.verify_ready, waitForCue=args.wait_for_cue, recording=args.recording,
        originalHash=hashlib.sha256(original).hexdigest()), indent=2))
    env = dict(os.environ)
    env.pop('ELECTRON_RUN_AS_NODE', None)
    env.pop('INSPECTORPRO_LLM_GATEWAY_CONFIG', None)
    result = dict(status='running')
    with (out / 'stdout.log').open('wb') as stdout, (out / 'stderr.log').open('wb') as stderr:
        child = subprocess.Popen([str(ROOT / 'desktop/node_modules/electron/dist/electron.exe'),
            str(Path(__file__).with_name('tour.cjs')), '--application', '--profile-file', str(profile_file),
            '--python', str(Path(sys.executable).with_name('python.exe'))], cwd=ROOT, env=env,
            stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
        result['pid'] = child.pid
        (out / 'launch.json').write_text(json.dumps(result))
        try:
            result.update(status='exited', code=child.wait(timeout=3600))
        except subprocess.TimeoutExpired:
            result['status'] = 'timeout'
            cleanup = subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'],
                capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW, timeout=30)
            result['forcedCleanupCode'] = cleanup.returncode
            result['code'] = child.wait(timeout=15)
    result['liveUnchanged'] = (live / LAYOUT).read_bytes() == original
    result['snapshotUnchanged'] = (out / 'store' / LAYOUT).read_bytes() == original
    (out / 'launch.json').write_text(json.dumps(result, indent=2))
    report_file = out / 'report.json'
    if report_file.exists():
        report = json.loads(report_file.read_text())
        if report.get('status') == 'running':
            report.update(status='interrupted', error='Application exited before tour completion',
                          applicationExitCode=result['code'])
            report_file.write_text(json.dumps(report, indent=2))


if __name__ == '__main__':
    main()
