"""Opt-in native Sage inspection and Stop test using a disposable gym copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import site
import sqlite3
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime.application_profile import load_application_profile
from desktop.runtime.codex_config import validate_package
from desktop.runtime.codex_credentials import (
    credential_target, delete_test_api_key, store_test_api_key, validate_key,
)
from desktop.runtime.profile import local_path
from tools import codex_desktop_pack as pack


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Authorize the selected paid native scenario on disposable copies')
    parser.add_argument('--cancel-only', action='store_true', help='One paid cancellation check; do not repeat completed conversation tests')
    parser.add_argument('--memory-check', action='store_true', help='Three completed turns: enforced memory, reload, and document switching')
    parser.add_argument('--reliability-check', choices=['startup', 'recovery', 'editing', 'authoring', 'editor-change'], help='Enforced-memory startup, recovery, approved-edit/undo, authoring or editor-change cancellation check on a copy')
    parser.add_argument('--load-workers', type=int, choices=range(5), default=0)
    parser.add_argument('--affinity-cpus', type=int, choices=[0, 2, 3, 4], default=0)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--release-root', type=Path, required=True, help='Verified dependency-only bundle, separate from the normal checkout')
    parser.add_argument('--api-key-file', type=Path, required=True)
    parser.add_argument('--provision-test-credential', action='store_true',
                        help='Read the supplied API key file and provision only this run\'s random test vault target')
    parser.add_argument('--port', type=int, default=8537)
    args = parser.parse_args(argv)
    if args.reliability_check and (args.memory_check or args.cancel_only):
        parser.error('Reliability checks are separate scenarios')
    if (args.load_workers or args.affinity_cpus) and args.reliability_check != 'startup':
        parser.error('Controlled load is restricted to the startup scenario')
    if args.load_workers and not args.affinity_cpus:
        parser.error('Load workers require explicit limited CPU affinity')
    if args.memory_check and args.cancel_only:
        parser.error('Memory/switch and cancellation checks are separate scenarios')
    if not args.live:
        parser.error('Explicit --live approval is required for paid inference and a native test window')
    if not args.provision_test_credential:
        parser.error('Explicit --provision-test-credential approval is required to read the API key file and use a test vault target')
    return args


def read_test_api_key(file):
    try:
        from dotenv import dotenv_values
        values = dotenv_values(file, interpolate=False)
        try:
            return validate_key(values.get('INSPECTORPRO_CODEX_API_KEY') or values.get('OPENAI_API_KEY'))
        finally:
            values.clear()
    except Exception:
        raise ValueError('desktop_codex_test_api_key_unavailable') from None


def prepare_test_profile(args, output, release, profile_id, package_sha256):
    if output.exists() or ROOT not in output.parents:
        raise ValueError('Use a fresh output directory inside the repository')
    if output == release or release in output.parents or output in release.parents:
        raise ValueError('Test output and release must not overlap')
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    prepare = subprocess.run([sys.executable, str(ROOT / 'desktop/tools/prepare-application-check.py'),
        '--destination', str(output), '--port', str(args.port), '--layout-id', 'fl-private-gym-20261007'],
        cwd=ROOT, capture_output=True, timeout=90, creationflags=flags)
    if prepare.returncode:
        raise RuntimeError(prepare.stderr.decode('utf-8', errors='replace')[-2000:])
    if args.memory_check:
        prepare_second_layout(output)
    file = output / 'profile.json'
    profile = load_application_profile(file).value
    if local_path(profile['dataRoot']) != output or local_path(profile['facilityRoot']) != output / 'facility':
        raise ValueError('desktop_codex_test_profile_not_isolated')
    profile['profileId'] = profile_id
    profile['codexRuntime'] = {
        'schemaVersion': 1, 'model': 'gpt-5.5', 'allowPaidInference': True,
        'editPreviews': args.reliability_check in {'editing', 'authoring'},
        'dependencyRoot': str(release / pack.DEPS),
        'packageSha256': package_sha256,
        'binary': str(release / pack.DEPS / 'codex_cli_bin/bin/codex.exe'),
        'pilotRoot': str(output / 'codex-pilot'), 'credentialTarget': credential_target(profile_id),
    }
    pack.atomic_bytes(file, pack.canonical(profile))
    validated = load_application_profile(file)
    validate_package(validated.value['codexRuntime'], ROOT)
    return validated


def prepare_second_layout(output):
    from ai_inspector.facility_layout.repository import _canonical_json_bytes
    relative = Path('layouts/local/site-local/layouts')
    other_id = 'fl-reference-manual-20260812'
    original = ROOT / '.runtime/facility-layout' / relative / (other_id + '.json')
    data = original.read_bytes()
    document = json.loads(data)
    target = output / 'facility' / relative
    (target / original.name).write_bytes(data)
    registry_path = target / 'registry.json'
    registry = json.loads(registry_path.read_text(encoding='utf-8'))
    source_registry = json.loads((original.parent / 'registry.json').read_text(encoding='utf-8'))
    registry['layouts'].extend(row for row in source_registry['layouts'] if row['layoutId'] == other_id)
    registry_path.write_bytes(_canonical_json_bytes(registry))
    (output / 'second-layout.json').write_text(json.dumps({'layoutId': other_id,
        'originalPath': str(original), 'copyPath': str(target / original.name),
        'sha256': hashlib.sha256(data).hexdigest(), 'name': document['displayName'],
        'zones': len(document['zones']), 'assets': len(document['placements'])}), encoding='utf-8')


def test_environment(args, output, source=None):
    env = dict(os.environ if source is None else source)
    for name in list(env):
        upper = name.upper()
        if (upper.startswith(('ELECTRON_', 'INSPECTORPRO_CODEX_', 'CODEX_'))
                or upper in {'NODE_OPTIONS', 'INSPECTORPRO_LLM_GATEWAY_CONFIG', 'PYTHONPATH', 'OPENAI_API_KEY'}):
            env.pop(name)
    env.update({
        'PYTHONPATH': site.getusersitepackages(),
        'INSPECTORPRO_CODEX_DESKTOP_CANCEL_ONLY': '1' if args.cancel_only else '0',
        'INSPECTORPRO_CODEX_DESKTOP_MEMORY_CHECK': '1' if args.memory_check else '0',
        'INSPECTORPRO_FACILITY_PRIVATE_ASSETS': '1',
        'INSPECTORPRO_MEMORY_V1_MODE': 'enforce' if args.memory_check or args.reliability_check else 'off',
        'INSPECTORPRO_MEMORY_DB_PATH': str(output / 'memory.sqlite'),
        'INSPECTORPRO_METRICS_DB': str(output / 'metrics.sqlite'),
        'INSPECTORPRO_CHAT_FEEDBACK_DB_PATH': str(output / 'feedback.sqlite'),
        'INSPECTORPRO_PARTS_MANUAL_ROOT': str(output / 'parts-manual'),
        'INSPECTORPRO_OPERATIONS_MANUAL_ROOT': str(output / 'operations-manual'),
        'INSPECTORPRO_SPECIFICATION_SHEET_ROOT': str(output / 'specification-sheet'),
        'INSPECTORPRO_WORK_INSTRUCTION_ROOT': str(output / 'work-instruction'),
        'INSPECTORPRO_CHAT_STREAMING': '0',
        'INSPECTORPRO_STREAMING_AGENTS': 'sage',
    })
    return env


def application_code_files(root):
    """Hash code, not generated resources, environment files or mutable stores."""
    paths = {root / name for name in ('server.py', 'run_app.py', 'requirements.txt',
        'desktop/package.json', 'desktop/package-lock.json',
        'tools/check_codex_sage_desktop.py', 'tools/codex_desktop_reliability.py',
        'tools/codex_desktop_pack.py')}
    suffixes = {'.py', '.cjs', '.mjs', '.js', '.json', '.css', '.html', '.wasm'}
    for name in ('ai_inspector', 'static', 'desktop/src', 'desktop/runtime', 'desktop/tools'):
        for current, folders, files in os.walk(root / name, followlinks=False):
            directory = local_path(current)
            folders[:] = sorted(name for name in folders if name not in {'__pycache__', 'node_modules', '.runtime'})
            for folder in folders:
                local_path(directory / folder)
            paths.update(directory / name for name in files
                         if Path(name).suffix.lower() in suffixes and not name.lower().startswith('.env'))
    records = []
    for path in sorted(paths):
        path = local_path(path)
        if path.is_file():
            records.append({'path': path.relative_to(root).as_posix(),
                            'bytes': path.stat().st_size, 'sha256': pack.digest(path)})
    if not {'server.py', 'desktop/src/entry.cjs'} <= {row['path'] for row in records}:
        raise ValueError('desktop_codex_normal_application_code_missing')
    return records


def main(argv=None):
    args = parse_args(argv)
    output = local_path(args.output_root.absolute())
    release = local_path(args.release_root.absolute())
    if output.exists() or ROOT not in output.parents:
        raise ValueError('Use a fresh output directory inside the repository')
    manifest = pack.verify_bundle(release)
    pack.separate(ROOT, release)
    before = application_code_files(ROOT)
    profile_id = 'codex-test-' + uuid.uuid4().hex
    profile = prepare_test_profile(args, output, release, profile_id, manifest['packageSha256'])
    binary = Path(profile.value['codexRuntime']['binary'])
    env = test_environment(args, output)
    evidence = {'schemaVersion': 1, 'appRoot': str(ROOT), 'releaseRoot': str(release),
                'packageSha256': manifest['packageSha256'], 'before': before,
                'beforeSha256': hashlib.sha256(pack.canonical(before)).hexdigest(), 'status': 'running'}
    evidence_file = output / 'application-code-evidence.json'
    pack.atomic_bytes(evidence_file, pack.canonical(evidence))
    provisioned = False
    try:
        key = read_test_api_key(args.api_key_file)
        try:
            store_test_api_key(profile_id, key)
            provisioned = True
        finally:
            del key
        try:
            result = run_native(args, output, release, binary, env)
        finally:
            evidence['status'] = 'failed'
            try:
                after = application_code_files(ROOT)
                evidence.update(after=after, afterSha256=hashlib.sha256(pack.canonical(after)).hexdigest(),
                                applicationCodeUnchanged=before == after,
                                dependencyBundleUnchanged=pack.verify_bundle(release) == manifest)
                if evidence['applicationCodeUnchanged'] and evidence['dependencyBundleUnchanged']:
                    evidence['status'] = 'verified'
            except Exception:
                evidence['error'] = 'desktop_codex_evidence_verification_failed'
            pack.atomic_bytes(evidence_file, pack.canonical(evidence))
    finally:
        if provisioned:
            delete_test_api_key(profile_id)
    result['applicationCodeEvidence'] = str(evidence_file)
    if evidence['status'] != 'verified':
        result.update(status='failed', error='desktop_codex_tested_code_or_bundle_changed')
    pack.atomic_bytes(output / 'codex-desktop-acceptance.json', pack.canonical(result))
    if args.reliability_check:
        print(json.dumps({key: result.get(key) for key in
            ('status', 'scenario', 'elapsedSeconds', 'error', 'loadWorkers', 'affinityCpus', 'loadResults', 'loadStopped')}, indent=2))
    else:
        print(json.dumps(result, indent=2))
    return 0 if result['status'] == 'passed' else 1


def run_native(args, output, release, binary, env):
    flags = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
    command = [str(ROOT / 'desktop/node_modules/electron/dist/electron.exe'),
        str(ROOT / 'desktop/src/entry.cjs'), '--application', '--profile-file', str(output / 'profile.json'),
        '--python', sys.executable, '--codex-acceptance-output', str(output)]
    if args.reliability_check:
        from tools.codex_desktop_reliability import run_reliability
        return run_reliability(command, env, output, binary, args.reliability_check,
                               args.load_workers, args.affinity_cpus)
    result = {'status': 'running', 'model': 'gpt-5.5', 'cancelOnly': args.cancel_only,
        'memoryCheck': args.memory_check, 'startedAt': time.time()}
    with (output / 'electron.stdout.log').open('wb') as stdout, (output / 'electron.stderr.log').open('wb') as stderr:
        child = subprocess.Popen(command, cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
            stdout=stdout, stderr=stderr, creationflags=flags)
        result['pid'] = child.pid
        (output / 'launcher.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
        try:
            result['exitCode'] = child.wait(timeout=600)
        except subprocess.TimeoutExpired:
            result['timeout'] = True
            subprocess.run(['taskkill', '/PID', str(child.pid), '/T', '/F'], capture_output=True,
                timeout=30, creationflags=flags)
            result['exitCode'] = child.wait(timeout=15)
    try:
        report = json.loads((output / 'codex-ui-check.json').read_text(encoding='utf-8'))
        runtime = json.loads((output / 'last-application-run.json').read_text(encoding='utf-8'))
        cleanups = [item.get('cleanup') or {} for item in runtime.get('backends', [])]
        from tools.codex_desktop_reliability import clean_desktop_shutdown
        result['cleanupConfirmed'] = bool(cleanups) and all(clean_desktop_shutdown(item) for item in cleanups)
        result['uiStatus'] = report['status']
        result['sourceUnchanged'] = report['sourceUnchanged']
        result['copyUnchanged'] = report['copyUnchanged']
        result['saveCalls'] = report['saveCalls']
        journal = output / 'codex-pilot/pilot.sqlite'
        if not journal.is_file():
            raise RuntimeError('No runtime journal: test failed before inference')
        with sqlite3.connect(journal) as db:
            result['journal'] = [{'turnId': row[0], 'status': row[1], 'code': (json.loads(row[2]) if row[2] else {}).get('code'), 'binding': row[3]}
                for row in db.execute('SELECT turn_id,status,result,binding FROM turns ORDER BY updated')]
            result['sessionCount'] = db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
        result['sameThreadResumed'] = (not args.cancel_only and result['sessionCount'] == 1
            and len(report['turns']) >= 2 and len({t.get('conversationId') for t in report['turns']}) == 1)
        expected = ['interrupted'] if args.cancel_only else ['completed', 'completed', 'interrupted']
        result['cancellationConfirmed'] = [t['status'] for t in result['journal']] == expected
        scenario_passed = (args.cancel_only or result['sameThreadResumed']) and result['cancellationConfirmed']
        if args.memory_check:
            entries = result['journal']
            resume_timeline = (report['turns'][1].get('terminal', {}).get('final', {}).get('codex_inspection', {}).get('runtimeTimeline', [])
                if len(report['turns']) >= 2 else [])
            result['sameThreadResumed'] = (len(entries) == 3 and entries[0]['binding'] == entries[1]['binding']
                and any(row['phase'] == 'thread/resume:done' for row in resume_timeline))
            result['documentRebound'] = len(entries) == 3 and entries[1]['binding'] != entries[2]['binding'] and result['sessionCount'] == 2
            result['secondLayoutUnchanged'] = report.get('secondSourceUnchanged') and report.get('secondCopyUnchanged')
            result['memoryCommitted'] = all(t.get('terminal', {}).get('final', {}).get('memory', {}).get('mode') == 'enforce' for t in report['turns'])
            with sqlite3.connect(output / 'memory.sqlite') as db:
                memory_rows = db.execute('SELECT status,model_metadata_json,context_manifest_id FROM memory_turns ORDER BY sequence').fetchall()
                result['memoryAudit'] = [{'status': row[0], 'model': json.loads(row[1]), 'hasManifest': bool(row[2])} for row in memory_rows]
            result['memoryAuditVerified'] = (len(memory_rows) == 3 and all(row['status'] == 'committed'
                and row['model'].get('runtime') == 'codex_app_server' and row['model'].get('model') == 'gpt-5.5'
                and row['hasManifest'] for row in result['memoryAudit']))
            scenario_passed = (result['sameThreadResumed'] and result['documentRebound'] and result['secondLayoutUnchanged']
                and report.get('switchBlockedWhileBusy') and report.get('reloadRestoredConversation')
                and [t['status'] for t in entries] == ['completed'] * 3 and result['memoryCommitted'] and result['memoryAuditVerified'])
        passed = (result['exitCode'] == 0 and result['uiStatus'] == 'passed' and result['cleanupConfirmed']
            and result['sourceUnchanged'] and result['copyUnchanged'] and result['saveCalls'] == 0
            and scenario_passed)
        result['status'] = 'passed' if passed else 'failed'
    except (OSError, ValueError, KeyError, RuntimeError, sqlite3.Error) as error:
        result.update(status='failed', reportError=type(error).__name__)
    result['elapsedSeconds'] = round(time.time() - result['startedAt'], 3)
    (output / 'launcher.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    return result


if __name__ == '__main__':
    raise SystemExit(main())
