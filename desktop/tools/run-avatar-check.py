"""Run isolated native avatar acceptance, with all child consoles hidden."""
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--electron', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8497)
    args = parser.parse_args()
    if not args.electron.is_file(): raise ValueError(f'Electron executable unavailable: {args.electron}')
    output = ROOT / '.runtime' / ('avatar-native-' + time.strftime('%Y%m%d-%H%M%S'))
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    subprocess.run([sys.executable, str(ROOT / 'desktop/tools/prepare-application-check.py'),
                    '--destination', str(output), '--port', str(args.port)], cwd=ROOT,
                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=flags, check=True)
    env = dict(os.environ)
    env.pop('ELECTRON_RUN_AS_NODE', None)
    with (output / 'electron.log').open('wb') as log:
        process = subprocess.Popen([str(args.electron), str(ROOT / 'desktop/tools/application-avatar-check.cjs'),
                                 '--profile-file', str(output / 'profile.json'), '--python', sys.executable,
                                 '--acceptance-output', str(output / 'evidence')], cwd=ROOT, env=env,
                                stdout=log, stderr=log, creationflags=flags)
        try:
            process.wait(timeout=480)
        except subprocess.TimeoutExpired:
            # This process and its children belong only to this isolated test.
            subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                           stdout=log, stderr=log, creationflags=flags, timeout=30, check=True)
            process.wait(timeout=15)
    report_file = output / 'evidence/avatar-check.json'
    report = json.loads(report_file.read_text()) if report_file.is_file() else {}
    result = {'output': str(output), 'exitCode': process.returncode, 'status': report.get('status', 'no-stage-report')}
    (output / 'launcher-result.json').write_text(json.dumps(result, indent=2))
    os.write(1, (json.dumps(result) + '\n').encode())
    return 0 if result['exitCode'] == 0 and result['status'] == 'passed' else 1


if __name__ == '__main__': sys.exit(main())
