"""Unelevated, isolated acceptance of the normal desktop application entry.

Creates a fresh marked fixture/profile, seeds its offline proposal, and launches
the installed pinned Electron binary. It never changes a live store, elevates,
disables Chromium sandboxing, or stops a process discovered through a port.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
LAYOUT = 'fl-reference-manual-20260812'
CHECKS = ('fullApplicationAndIsolation', 'twoEditsCloseCancel', 'uncoveredProcessMapBlocksLifecycle', 'applyPendingRestart', 'undoPendingRestart', 'savedLayoutUnchanged', 'transactionRequestsOnce')
INPUT_LABELS = ('attached', 'manual-close-cancel', 'uncovered-workflow-refused', 'apply-close-cancel', 'apply-reconciled', 'undo-close-cancel', 'undo-reconciled')
INPUT_TRUE = ('facilityInputAllowed', 'attached', 'nativeInertSupported', 'facilityConnected')
INPUT_FALSE = ('gateBlocked', 'forcedLock', 'frozen', 'inertAncestor')


def now(): return datetime.now(timezone.utc).isoformat()


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temporary.open('x', encoding='utf-8') as stream:
        json.dump(value, stream, indent=2); stream.write('\n'); stream.flush(); os.fsync(stream.fileno())
    try: os.replace(temporary, path)
    except OSError:
        # Preserve a unique flushed diagnostic even when a reader locks the
        # usual report name. Never replace an unrelated or existing report.
        fallback = path.with_name(path.stem + '.final-' + uuid.uuid4().hex + '.json')
        os.replace(temporary, fallback)
        print('Diagnostic retained at ' + str(fallback), file=sys.stderr, flush=True)
        raise


def read(path):
    if path.stat().st_size > 32 * 1024 * 1024: raise ValueError('Oversized acceptance evidence')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def digest(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()


def capture(stream, target):
    state = {'eof': False, 'closed': False, 'error': None}
    def consume():
        log = None
        try:
            try: log = target.open('ab', buffering=0)
            except OSError as error: state['error'] = str(error)
            while True:
                chunk = stream.read1(65536)
                if not chunk: state['eof'] = True; break
                if log:
                    try:
                        remaining = memoryview(chunk)
                        while remaining:
                            count = log.write(remaining)
                            if not count: raise OSError('Diagnostic write made no progress')
                            remaining = remaining[count:]
                    except OSError as error:
                        state['error'] = str(error)
                        try: log.close()
                        except OSError: pass
                        log = None
            if log: os.fsync(log.fileno())
        except BaseException as error: state['error'] = str(error)
        finally:
            if log:
                try: log.close()
                except OSError as error: state['error'] = str(error)
            if state['eof']:
                try: stream.close(); state['closed'] = True
                except OSError as error: state['error'] = str(error)
    thread = threading.Thread(target=consume, daemon=True, name='runtime-launcher-log')
    thread.start(); return thread, state


def run_stage(command, output, *, env=None, timeout=240, application_window=False):
    output.mkdir(parents=True, exist_ok=False)
    result = {'status': 'starting', 'startedAt': now(), 'command': list(map(str, command)),
              'terminationConfirmed': False, 'stdoutClosed': False, 'stderrClosed': False, 'forced': False,
              'windowMode': 'application-controlled' if application_window else 'hidden-helper'}
    process = None; readers = []
    for name in ('stdout.log', 'stderr.log'): (output / name).touch(exist_ok=False)
    write(output / 'process-result.json', result)
    try:
        kwargs = {}
        if os.name == 'nt':
            kwargs = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP}
            if not application_window:
                info = subprocess.STARTUPINFO(); info.dwFlags |= subprocess.STARTF_USESHOWWINDOW; info.wShowWindow = subprocess.SW_HIDE
                kwargs['startupinfo'] = info
            # STARTF_USESHOWWINDOW/SW_HIDE overrides a GUI process's first
            # ShowWindow call. Only background helpers should inherit it.
        process = subprocess.Popen(list(map(str, command)), cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE, **kwargs)
        result.update(status='running', processId=process.pid)
        readers.append(capture(process.stdout, output / 'stdout.log'))
        readers.append(capture(process.stderr, output / 'stderr.log'))
        write(output / 'process-result.json', result)
        result['exitCode'] = process.wait(timeout=timeout)
        result['status'] = 'passed' if result['exitCode'] == 0 else 'failed'
    except BaseException as error:
        result.update(status='failed', error={'type': type(error).__name__, 'message': str(error)})
    finally:
        if process is not None:
            if process.poll() is None:
                result['forced'] = True
                try:
                    process.terminate(); process.wait(timeout=10)
                except (OSError, subprocess.TimeoutExpired):
                    try: process.kill(); process.wait(timeout=10)
                    except (OSError, subprocess.TimeoutExpired) as error: result['cleanupError'] = str(error)
            result['terminationConfirmed'] = process.poll() is not None
            result['exitCode'] = process.poll()
            for name, pair in zip(('stdout', 'stderr'), readers):
                thread, state = pair; thread.join(timeout=5)
                result[name + 'EOF'] = not thread.is_alive() and state['eof']
                result[name + 'Closed'] = not thread.is_alive() and state['closed']
                if state['error']: result[name + 'Error'] = state['error']
            for name in ('stdout', 'stderr')[len(readers):]:
                # No reader was started for this handle. Closing it after owned
                # process termination is cleanup, not proof of diagnostic EOF.
                try: getattr(process, name).close(); result[name + 'Closed'] = True
                except OSError as error: result[name + 'Error'] = str(error)
        if (not result['terminationConfirmed'] or not result['stdoutClosed'] or not result['stderrClosed']
                or not result.get('stdoutEOF') or not result.get('stderrEOF')
                or result.get('stdoutError') or result.get('stderrError') or result['forced']): result['status'] = 'failed'
        result['finishedAt'] = now(); write(output / 'process-result.json', result)
    return result


def validate_native(report, final):
    if (report.get('schemaVersion') != 1 or report.get('mode') != 'normal-entry-full-application'
            or report.get('status') != 'passed' or any(report.get('checks', {}).get(key) != 'passed' for key in CHECKS)
            or report.get('checks', {}).get('recoveredScreenshot') != 'captured-awaiting-visual-review'
            or report.get('generalEditing') is not False or report.get('researchBrowsing') is not False):
        raise ValueError('Native report does not establish the requested normal-application checkpoint')
    isolation = report.get('isolation', {})
    if isolation != {'sandbox': True, 'contextIsolation': True, 'nodeIntegration': False, 'webSecurity': True,
                     'renderer': {'requireType': 'undefined', 'processType': 'undefined'}}:
        raise ValueError('Native isolation evidence is incomplete')
    if (final.get('schemaVersion') != 1 or final.get('status') != 'passed' or final.get('finalClose') != 'closed-without-save'
            or final.get('discardFinalized') is not True or any(final.get('cleanup', {}).get(key) is not True
                for key in ('terminationConfirmed', 'stdioClosed', 'resourcesClosed'))):
        raise ValueError('Final Close/discard/backend cleanup receipt is incomplete')
    if any(type(evidence.get('saveCalls')) is not int or evidence['saveCalls'] != 0 for evidence in (report, final)):
        raise ValueError('Zero Save calls are required in both native and final receipts')
    input_checks = report.get('facilityInputChecks', [])
    if (not isinstance(input_checks, list) or [item.get('label') for item in input_checks] != list(INPUT_LABELS)
            or any(any(item.get(key) is not True for key in INPUT_TRUE)
                   or any(item.get(key) is not False for key in INPUT_FALSE) for item in input_checks)):
        raise ValueError('Facility input must be positively verified after attachment and each recovery transition')
    requests = report.get('requests', {})
    transactions = requests.get('transactionRequests', {})
    if type(requests.get('saveCalls')) is not int or requests['saveCalls'] != 0 or not isinstance(transactions, dict) or len(transactions) != 5:
        raise ValueError('Complete zero-Save and single-execution request evidence is required')
    operations = []
    prefix = '/api/facility-layout-design/site-local/' + re.escape(LAYOUT)
    pattern = re.compile(prefix + r'/(?:proposals/[A-Za-z0-9_-]+/(apply/prepare)|transactions/[A-Za-z0-9_-]+/(apply/commit|apply/acknowledge|undo/prepare|undo/acknowledge))')
    for route, count in transactions.items():
        match = pattern.fullmatch(route)
        if not match or type(count) is not int or count != 1: raise ValueError('Unexpected or repeated transaction request')
        operations.append(next(value for value in match.groups() if value))
    if sorted(operations) != sorted(['apply/prepare', 'apply/commit', 'apply/acknowledge', 'undo/prepare', 'undo/acknowledge']):
        raise ValueError('Required transaction request is missing or duplicated')
    backends = final.get('backends', [])
    if (not isinstance(backends, list) or len(backends) < 3
            or len({item.get('instanceId') for item in backends}) != len(backends)
            or any(any(item.get('cleanup', {}).get(key) is not True for key in ('terminationConfirmed', 'stdioClosed', 'resourcesClosed')) for item in backends)):
        raise ValueError('Every owned backend instance requires confirmed cleanup')


def environment(output):
    allowed = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER', 'OS',
               'APPDATA', 'USERPROFILE'}
    env = {key: value for key, value in os.environ.items() if key.upper() in allowed}
    system = Path(os.environ.get('SystemRoot', r'C:\Windows'))
    env.update(PATH=os.pathsep.join([str(Path(sys.executable).parent), str(system / 'System32'), str(system)]),
               PYTHON_DOTENV_DISABLED='1', PYTHONUNBUFFERED='1', PYTHONDONTWRITEBYTECODE='1', ELECTRON_ENABLE_LOGGING='1')
    # Python resolves its existing user-site packages during interpreter startup.
    # Preserve that discovery context; seed/backend configure_environment then
    # redirects application writes before importing the actual application.
    # Electron sets userData explicitly from the isolated profile before ready.
    for name, folder in [('TEMP', 'temp'), ('TMP', 'temp'), ('LOCALAPPDATA', 'localappdata')]:
        target = output / 'launch-environment' / folder; target.mkdir(parents=True, exist_ok=True); env[name] = str(target)
    return env


def native_command(executable, profile_file, native_output, *, startup_diagnostics_only=False, research_check=False):
    return [executable, ROOT / 'desktop/src/entry.cjs', '--profile-file', profile_file, '--python', sys.executable,
            '--startup-diagnostics-output' if startup_diagnostics_only else '--acceptance-output', native_output] + (
                ['--research-acceptance-output', native_output] if research_check else [])


def validate_startup_diagnostics(report):
    if (report.get('schemaVersion') != 1 or report.get('mode') != 'managed-backend-startup-diagnostics'
            or report.get('status') != 'passed' or report.get('startupDiagnosticsOnly') is not True
            or report.get('runtimeVerified') is not True or report.get('startupDeadlineMs') != 45000
            or any(report.get(key) is not False for key in ('nativeAcceptance', 'applicationLoaded', 'facilityAttached',
                'editorExercised', 'screenshotCaptured', 'generalEditing', 'researchBrowsing'))
            or type(report.get('saveCalls')) is not int or report['saveCalls'] != 0 or report.get('error') is not None):
        raise ValueError('The result must establish startup diagnostics only, with no application or editing acceptance')
    if report.get('isolation') != {'sandbox': True, 'contextIsolation': True, 'nodeIntegration': False, 'webSecurity': True}:
        raise ValueError('Startup diagnostic isolation evidence is incomplete')
    cleanup = report.get('cleanup', {})
    if any(cleanup.get(key) is not True for key in ('terminationConfirmed', 'stdioClosed', 'resourcesClosed')) or cleanup.get('forced') is not False:
        raise ValueError('Startup diagnostics require confirmed graceful owned-backend cleanup')
    backends = report.get('backends', [])
    if not isinstance(backends, list) or len(backends) != 1:
        raise ValueError('Startup diagnostics must describe exactly one owned backend instance')
    backend = backends[0]
    if (backend.get('startupDiagnosticsEnabled') is not True or not backend.get('instanceId')
            or backend.get('instanceId') != cleanup.get('instanceId') or backend.get('cleanup') != cleanup
            or type(backend.get('processId')) is not int or backend['processId'] < 1 or backend['processId'] != cleanup.get('processId')
            or backend.get('runtime', {}).get('instanceId') != backend['instanceId']
            or backend.get('runtime', {}).get('processId') != backend['processId']
            or backend.get('failure', 'missing') is not None or backend.get('diagnosticErrors') != []
            or type(backend.get('importTimingLines')) is not int or backend['importTimingLines'] < 1
            or not isinstance(backend.get('timings'), dict)
            or not isinstance(backend.get('startupCheckpoints'), dict)):
        raise ValueError('Owned startup instrumentation and identity evidence is incomplete')
    def time_value(value):
        return type(value) in (int, float) and 0 <= value < float('inf')
    timings = backend['timings']; checkpoints = backend['startupCheckpoints']
    ordered = [timings.get(key) for key in ('readyObservedElapsedMs', 'runtimeVerifiedElapsedMs',
               'shutdownRequestedElapsedMs', 'processExitElapsedMs', 'stdioClosedElapsedMs')]
    if (not time_value(timings.get('spawnStartedUnixMs')) or timings['spawnStartedUnixMs'] == 0
            or any(not time_value(value) for value in ordered) or ordered != sorted(ordered)
            or not time_value(backend.get('startupElapsedMs')) or backend['startupElapsedMs'] != timings['runtimeVerifiedElapsedMs']):
        raise ValueError('Owned startup and shutdown timings are incomplete')
    records = checkpoints.get('records', [])
    if (any(any(type(value.get(key)) is not int or value[key] != 0 for key in ('invalidCount', 'foreignCount', 'truncatedCount'))
            for value in (checkpoints, backend.get('diagnosticErrorCounts', {})))
            or not isinstance(records, list) or not records or checkpoints.get('lastPhase') != records[-1].get('phase')
            or not any(item.get('phase') == 'application-ready' for item in records)
            or any(item.get('instanceId') != backend['instanceId'] or item.get('processId') != backend['processId']
                or type(item.get('sequence')) is not int or item['sequence'] < 1
                or not time_value(item.get('elapsedMs')) or not time_value(item.get('observedElapsedMs')) for item in records)):
        raise ValueError('Owned phase checkpoints or diagnostic-error evidence is incomplete')
    files = backend.get('diagnosticsFiles', {})
    if (files.get('imports', {}).get('metadataValid') is not True
            or files.get('stacks', {}).get('baselinePresent') is not True
            or type(files.get('stacks', {}).get('sizeBytes')) is not int or files['stacks']['sizeBytes'] <= 0
            or any(files.get(key, {}).get('exists') is not True or not isinstance(files[key].get('path'), str)
                   for key in ('stacks', 'imports'))):
        raise ValueError('Startup diagnostics did not retain validated stack and import metadata references')


def validate_research(report, output):
    if (report.get('schemaVersion') != 1 or report.get('status') not in {'passed', 'pending-native-composite'}
            or report.get('stage') != 'complete' or report.get('engineChecksPassed') is not True
            or report.get('exactFrameRetained') is not True or report.get('localNetworkBlocked') is not True
            or type(report.get('saveCalls')) is not int or report['saveCalls'] != 0 or report.get('error') is not None):
        raise ValueError('Research acceptance evidence is incomplete')
    checks = report.get('checks', {})
    if any(checks.get(key) is not True for key in ('publicHTTPSAndIsolation', 'boundsHideReopenAndOverlay', 'realMeshesAndLibrary')):
        raise ValueError('Every research engine gate is required')
    preferences = report.get('isolation', {})
    if (any(preferences.get(key) is not True for key in ('sandbox', 'contextIsolation', 'webSecurity'))
            or preferences.get('nodeIntegration') is not False or preferences.get('preload')):
        raise ValueError('Research must have no privileged preload or Node access')
    network = report.get('network', [])
    if len(network) != 4 or any(item.get('blocked') is not True for item in network):
        raise ValueError('Every private-network probe must be blocked')
    meshes = report.get('meshes', {})
    audit = meshes.get('transformAudit', {})
    if (meshes.get('realPlacements') != 827 or meshes.get('assetGroups') != 37
            or audit.get('status') != 'match' or audit.get('auditedPlacementCount') != 827
            or audit.get('transformMismatchCount') != 0 or audit.get('missingPlacementCount') != 0):
        raise ValueError('Real reference GLBs and exact placement transforms are required')
    library = report.get('library', {})
    if library.get('open') is not True or type(library.get('cards')) is not int or library['cards'] < 37:
        raise ValueError('Actual asset library cards are required')
    complete = report.get('status') == 'passed'
    if report.get('nativeAcceptance') is not complete or report.get('nativeCompositeAvailable') is not complete:
        raise ValueError('Missing native composite capture cannot be reported as accepted')
    if complete:
        captures = {item.get('name'): item for item in report.get('captures', [])}
        for name in ('research-wide.png', 'research-narrow.png'):
            if captures.get(name, {}).get('method') not in {'owned-window-desktop-capturer', 'PrintWindow-owned-hwnd'}:
                raise ValueError('A native owned-window capture is required at each size')
            image = output / name
            if not image.is_file() or image.stat().st_size < 1000 or image.read_bytes()[:8] != b'\x89PNG\r\n\x1a\n':
                raise ValueError('Native composite PNG is missing or invalid')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--electron-desktop', type=Path, required=True)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8462)
    parser.add_argument('--validate-only', action='store_true')
    parser.add_argument('--startup-diagnostics-only', action='store_true')
    parser.add_argument('--research-check', action='store_true')
    args = parser.parse_args(argv)
    if args.research_check and args.startup_diagnostics_only:
        parser.error('Research checks require the full application')
    if not args.electron_desktop.is_absolute() or not args.output_root.is_absolute() or not 1024 <= args.port <= 65535:
        parser.error('Explicit absolute local paths and port 1024–65535 are required')
    spec = importlib.util.spec_from_file_location('runtime_launch_common', Path(__file__).with_name('run-rendering-check.py'))
    common = importlib.util.module_from_spec(spec); spec.loader.exec_module(common)
    source = common.backend.no_links(Path(read(ROOT / 'desktop-checkpoint.json')['source']))
    args.output_root = common.backend.no_links(args.output_root)
    if args.output_root == source or source in args.output_root.parents or args.output_root in source.parents:
        raise ValueError('Diagnostic output may not overlap the live source workspace')
    binary = common.resolve_electron(args.electron_desktop)
    if binary['version'] != read(ROOT / 'desktop/package.json')['devDependencies']['electron']:
        raise ValueError('The runtime snapshot and installed binary must use the same exact Electron pin')
    for target in (ROOT / 'desktop/src/entry.cjs', ROOT / 'desktop/runtime/create_profile.py', ROOT / 'desktop/tools/seed-runtime-proposal.py'):
        if not target.is_file(): raise ValueError('Prepared runtime file is missing: ' + str(target))
    if args.validate_only:
        print(json.dumps({'status': 'arguments-validated', 'nativeLaunched': False, 'electron': binary, 'snapshot': str(ROOT),
                          'startupDiagnosticsOnly': args.startup_diagnostics_only})); return 0
    if os.name != 'nt': raise ValueError('This launcher requires an ordinary Windows desktop terminal')
    import ctypes
    if ctypes.windll.shell32.IsUserAnAdmin(): raise ValueError('Run from an ordinary, unelevated PowerShell terminal')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-') + uuid.uuid4().hex[:8]
    output = args.output_root / ('inspectorpro-runtime-' + stamp); output.mkdir(parents=True, exist_ok=False)
    data = ROOT / '.runtime/desktop-spike' / ('runtime-native-' + stamp)
    profile_file = output / 'profile.json'; native_output = output / 'native'
    profile_id = 'runtime-native-' + stamp
    source_layout = source / '.runtime/facility-layout/layouts/local/site-local/layouts' / (LAYOUT + '.json')
    isolated_layout = data / 'facility/layouts/local/site-local/layouts' / (LAYOUT + '.json')
    report = {'schemaVersion': 1, 'mode': 'managed-backend-startup-diagnostic-launcher' if args.startup_diagnostics_only else 'normal-desktop-native-launcher', 'status': 'running', 'startedAt': now(),
              'administratorToken': False, 'electron': binary, 'snapshot': str(ROOT), 'dataRoot': str(data), 'profileFile': str(profile_file),
              'generalEditing': False, 'researchBrowsing': False, 'stages': [],
              'startupDiagnosticsOnly': args.startup_diagnostics_only,
              'visualReview': 'not-applicable' if args.startup_diagnostics_only else 'pending'}
    if args.startup_diagnostics_only: report['nativeAcceptance'] = False
    env = environment(output)
    def stage(name, command, timeout=240, application_window=False):
        report['stage'] = name; write(output / 'native-launch.json', report)
        print('Running ' + name + '; logs: ' + str(output / name), flush=True)
        result = run_stage(command, output / name, env=env, timeout=timeout, application_window=application_window)
        report['stages'].append({'name': name, **result}); write(output / 'native-launch.json', report)
        if result['status'] != 'passed': raise RuntimeError(name + ' failed; inspect its retained process-result.json and logs')
    try:
        report['sourceHashBefore'] = digest(source_layout)
        stage('prepare-fixture', [sys.executable, '-B', ROOT / 'desktop/tools/prepare-facility-recovery-fixture.py', '--snapshot-root', ROOT,
              '--source-root', source, '--data-root', data, '--port', args.port, '--profile-id', profile_id])
        report['isolatedHashBefore'] = digest(isolated_layout)
        if report['isolatedHashBefore'] != report['sourceHashBefore']: raise ValueError('Copied layout differs from source')
        stage('create-profile', [sys.executable, '-B', ROOT / 'desktop/runtime/create_profile.py', '--profile-file', profile_file,
              '--data-root', data, '--profile-id', profile_id, '--port', args.port, '--acceptance-layout-id', LAYOUT])
        if not args.startup_diagnostics_only:
            stage('seed-offline-proposal', [sys.executable, '-B', ROOT / 'desktop/tools/seed-runtime-proposal.py', '--profile-file', profile_file])
        if digest(Path(binary['executable'])) != binary['sha256']: raise ValueError('Pinned Electron binary changed before launch')
        stage('native-process', native_command(binary['executable'], profile_file, native_output,
              startup_diagnostics_only=args.startup_diagnostics_only, research_check=args.research_check), timeout=900,
              application_window=not args.startup_diagnostics_only)
        if args.startup_diagnostics_only:
            diagnostic = read(native_output / 'startup-diagnostics-result.json'); validate_startup_diagnostics(diagnostic)
            report['diagnosticReport'] = str(native_output / 'startup-diagnostics-result.json')
            report['saveCalls'] = diagnostic['saveCalls']
            report['status'] = 'passed'; report['stage'] = 'complete-startup-diagnostics-only'
        else:
            native, final = read(native_output / 'runtime-integration-check.json'), read(native_output / 'runtime-final-result.json')
            validate_native(native, final)
            if not (native_output / 'full-application-recovered.png').is_file(): raise ValueError('Captured application screenshot is missing')
            report['nativeReport'] = str(native_output / 'runtime-integration-check.json')
            report['finalReceipt'] = str(native_output / 'runtime-final-result.json')
            report['saveCalls'] = final['saveCalls']
            if args.research_check:
                research = read(native_output / 'research-check.json')
                validate_research(research, native_output)
                report['researchReport'] = str(native_output / 'research-check.json')
            report['status'] = 'passed'; report['stage'] = 'complete-awaiting-visual-review'
            if args.research_check and research.get('nativeAcceptance') is not True:
                report['status'] = 'pending-native-composite'
    except BaseException as error:
        report['status'] = 'failed'; report['error'] = {'type': type(error).__name__, 'message': str(error)}
    finally:
        if args.startup_diagnostics_only and (native_output / 'startup-diagnostics-result.json').is_file():
            report['diagnosticReport'] = str(native_output / 'startup-diagnostics-result.json')
        for name, target in [('source', source_layout), ('isolated', isolated_layout)]:
            try: report[name + 'HashAfter'] = digest(target)
            except OSError as error: report[name + 'HashError'] = str(error)
        report['savedLayoutsUnchanged'] = all(report.get(name + 'HashBefore') is not None
            and report.get(name + 'HashAfter') == report[name + 'HashBefore'] for name in ('source', 'isolated'))
        if not report['savedLayoutsUnchanged']: report['status'] = 'failed'
        report['finishedAt'] = now(); write(output / 'native-launch.json', report)
        print(json.dumps({'status': report['status'], 'report': str(output / 'native-launch.json'),
                          'startupDiagnosticsOnly': args.startup_diagnostics_only, 'visualReview': report['visualReview']}), flush=True)
    return 0 if report['status'] == 'passed' else 1


if __name__ == '__main__':
    try: raise SystemExit(main())
    except Exception as error:
        print(type(error).__name__ + ': ' + str(error), file=sys.stderr, flush=True); raise SystemExit(1)
