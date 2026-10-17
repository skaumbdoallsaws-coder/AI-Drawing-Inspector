import ctypes
import json
from pathlib import Path
import re
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from desktop.runtime import codex_credentials as credentials
from tools import check_codex_sage_desktop as launcher

SECRET = 'test-only-launcher-api-key-' + 'x' * 32
TEST_ID = 'codex-test-' + 'a' * 32


def save_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def setup(tmp_path, monkeypatch):
    root, release = tmp_path / 'checkout', tmp_path / 'release'
    root.mkdir()
    (root / 'server.py').write_text('# normal application', encoding='utf-8')
    entry = root / 'desktop/src/entry.cjs'
    entry.parent.mkdir(parents=True)
    entry.write_text('// normal checkout entry', encoding='utf-8')
    binary = release / launcher.pack.DEPS / 'codex_cli_bin/bin/codex.exe'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fake-binary')
    library = root / 'library'
    library.mkdir()
    events = []
    monkeypatch.setattr(launcher, 'ROOT', root)
    monkeypatch.setattr(launcher.pack, 'verify_bundle', lambda path:
                        events.append(('verify', path)) or {'packageSha256': 'a' * 64})
    monkeypatch.setattr(launcher, 'validate_package', lambda config, path: events.append(('package', path)))
    def prepare(command, **kwargs):
        events.append(('prepare', command, kwargs))
        assert command[1] == str(root / 'desktop/tools/prepare-application-check.py')
        assert kwargs['cwd'] == root and kwargs['capture_output'] is True
        output = Path(command[command.index('--destination') + 1])
        output.mkdir()
        (output / 'facility').mkdir()
        profile = dict(schemaVersion=1, mode='application', profileId='application-check',
                       origin='http://127.0.0.1:8537', dataRoot=str(output), facilityRoot=str(output / 'facility'),
                       libraryRoot=str(library), backendId='11111111-1111-1111-1111-111111111111',
                       storeId='22222222-2222-2222-2222-222222222222', startupLayoutId='fl-private-gym-20261007')
        save_json(output / 'profile.json', profile)
        return SimpleNamespace(returncode=0, stdout=b'fixture-prepared', stderr=b'')
    monkeypatch.setattr(launcher.subprocess, 'run', prepare)
    monkeypatch.setattr(launcher, 'read_test_api_key', lambda file: events.append(('read-key', file)) or SECRET)
    monkeypatch.setattr(launcher, 'store_test_api_key', lambda target, key: events.append(('store', target, key)))
    monkeypatch.setattr(launcher, 'delete_test_api_key', lambda target: events.append(('delete', target)))
    environment = launcher.test_environment
    monkeypatch.setattr(launcher, 'test_environment', lambda args, output: environment(args, output, {
        'CODEX_HOME': 'personal', 'INSPECTORPRO_CODEX_API_KEY': 'inherited-key',
        'INSPECTORPRO_CODEX_READONLY_PILOT': '1', 'OPENAI_API_KEY': 'inherited-key',
        'INSPECTORPRO_CHAT_STREAMING': '1',
        'PYTHONPATH': 'live-checkout-bootstrap', 'PATH': 'test-path',
    }))
    def run(args, output, selected_release, selected_binary, env):
        events.append(('native', args, output, selected_release, selected_binary, env))
        return {'status': 'passed', 'scenario': args.reliability_check, 'captured': 'kept'}
    monkeypatch.setattr(launcher, 'run_native', run)
    def argv(name='run', extra=()):
        return ['--live', '--release-root', str(release), '--output-root', str(root / name),
                '--api-key-file', str(root / 'not-read.fixture'), '--provision-test-credential', *extra]
    return SimpleNamespace(root=root, release=release, binary=binary, events=events, argv=argv)


@pytest.mark.parametrize('missing', ['--release-root', '--live', '--provision-test-credential'])
def test_required_release_and_explicit_provisioning_reject_before_side_effects(setup, missing):
    args = setup.argv()
    index = args.index(missing)
    del args[index:index + (2 if missing == '--release-root' else 1)]
    with pytest.raises(SystemExit) as error:
        launcher.main(args)
    assert error.value.code == 2
    assert setup.events == []


def test_bad_release_is_verified_before_copy_key_read_or_vault_access(setup, monkeypatch):
    def reject(_): raise ValueError('bad-release')
    monkeypatch.setattr(launcher.pack, 'verify_bundle', reject)
    with pytest.raises(ValueError, match='bad-release'):
        launcher.main(setup.argv())
    assert setup.events == []
    assert not (setup.root / 'run').exists()


def test_missing_normal_entry_is_not_launched(setup):
    (setup.root / 'desktop/src/entry.cjs').unlink()
    with pytest.raises(ValueError, match='desktop_codex_normal_application_code_missing'):
        launcher.main(setup.argv())
    assert setup.events == [('verify', setup.release)]


@pytest.mark.parametrize('extra', [
    ['--memory-check', '--cancel-only'], ['--memory-check', '--reliability-check', 'recovery'],
    ['--load-workers', '1'], ['--reliability-check', 'editing', '--affinity-cpus', '2'],
    ['--reliability-check', 'editor-change', '--affinity-cpus', '2'],
    ['--reliability-check', 'startup', '--load-workers', '1'],
])
def test_existing_scenario_exclusivity_remains_before_side_effects(setup, extra):
    with pytest.raises(SystemExit) as error:
        launcher.main(setup.argv(extra=extra))
    assert error.value.code == 2
    assert setup.events == []


@pytest.mark.parametrize('scenario', ['startup', 'recovery', 'editing', 'editor-change'])
def test_reliability_scenarios_use_packaged_profile_and_exact_test_cleanup(setup, scenario, capsys):
    assert launcher.main(setup.argv(extra=['--reliability-check', scenario])) == 0
    profile = json.loads((setup.root / 'run/profile.json').read_text(encoding='utf-8'))
    profile_id = profile['profileId']
    assert re.fullmatch(r'codex-test-[a-f0-9]{32}', profile_id)
    config = profile['codexRuntime']
    assert config == {
        'schemaVersion': 1, 'model': 'gpt-5.5', 'allowPaidInference': True, 'editPreviews': scenario == 'editing',
        'dependencyRoot': str(setup.release / launcher.pack.DEPS), 'binary': str(setup.binary),
        'packageSha256': 'a' * 64,
        'pilotRoot': str(setup.root / 'run/codex-pilot'), 'credentialTarget': credentials.credential_target(profile_id),
    }
    assert profile['backendId'] == '11111111-1111-1111-1111-111111111111'
    assert profile['facilityRoot'] == str(setup.root / 'run/facility')
    assert SECRET not in json.dumps(profile)
    assert [row[0] for row in setup.events] == ['verify', 'prepare', 'package', 'read-key', 'store', 'native', 'verify', 'delete']
    assert ('package', setup.root) in setup.events
    assert setup.events[-1] == ('delete', profile_id)
    native = next(row for row in setup.events if row[0] == 'native')
    assert native[3:5] == (setup.release, setup.binary)
    env = native[5]
    assert env['INSPECTORPRO_MEMORY_V1_MODE'] == 'enforce'
    assert env['INSPECTORPRO_CHAT_STREAMING'] == '0'
    assert env['INSPECTORPRO_STREAMING_AGENTS'] == 'sage'
    assert 'INSPECTORPRO_CODEX_API_KEY' not in env and 'OPENAI_API_KEY' not in env
    assert 'INSPECTORPRO_CODEX_READONLY_PILOT' not in env and 'CODEX_HOME' not in env
    assert 'live-checkout-bootstrap' not in env['PYTHONPATH']
    output = capsys.readouterr()
    assert json.loads(output.out)['status'] == 'passed'
    assert SECRET not in output.out + output.err
    evidence = json.loads((setup.root / 'run/application-code-evidence.json').read_text())
    assert evidence['status'] == 'verified' and evidence['before'] == evidence['after']
    assert evidence['beforeSha256'] == evidence['afterSha256']


def test_each_run_gets_a_different_profile_and_vault_target(setup):
    launcher.main(setup.argv('first'))
    launcher.main(setup.argv('second'))
    stored = [row[1] for row in setup.events if row[0] == 'store']
    deleted = [row[1] for row in setup.events if row[0] == 'delete']
    assert len(set(stored)) == 2
    assert deleted == stored


@pytest.mark.parametrize('target', ['server.py', 'static/index.html', 'desktop/src/entry.cjs'])
def test_code_changed_during_native_run_invalidates_acceptance_and_still_cleans_vault(setup, monkeypatch, target):
    file = setup.root / target
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text('reviewed code', encoding='utf-8')
    def run(*args):
        file.write_text('changed during acceptance', encoding='utf-8')
        return {'status': 'passed'}
    monkeypatch.setattr(launcher, 'run_native', run)
    assert launcher.main(setup.argv()) == 1
    evidence = json.loads((setup.root / 'run/application-code-evidence.json').read_text())
    assert evidence['status'] == 'failed' and evidence['applicationCodeUnchanged'] is False
    result = json.loads((setup.root / 'run/codex-desktop-acceptance.json').read_text())
    assert result['status'] == 'failed' and result['error'] == 'desktop_codex_tested_code_or_bundle_changed'
    assert setup.events[-1][0] == 'delete'


def test_bundle_changed_during_native_run_invalidates_acceptance(setup, monkeypatch):
    count = 0
    def verify(_):
        nonlocal count
        count += 1
        return {'packageSha256': ('a' if count == 1 else 'b') * 64}
    monkeypatch.setattr(launcher.pack, 'verify_bundle', verify)
    assert launcher.main(setup.argv()) == 1
    evidence = json.loads((setup.root / 'run/application-code-evidence.json').read_text())
    assert evidence['dependencyBundleUnchanged'] is False
    assert setup.events[-1][0] == 'delete'


def test_evidence_never_reads_environment_or_generated_user_content(setup, monkeypatch):
    excluded = [setup.root / '.env', setup.root / 'static/.env.json',
                setup.root / 'generated/industrial_assets/local_library/catalog.json']
    for file in excluded:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('not code; do not read', encoding='utf-8')
    original = launcher.pack.digest
    def guarded(file):
        assert file not in excluded
        return original(file)
    monkeypatch.setattr(launcher.pack, 'digest', guarded)
    records = launcher.application_code_files(setup.root)
    assert {row['path'] for row in records} == {'server.py', 'desktop/src/entry.cjs'}


@pytest.mark.parametrize('error', [RuntimeError('launch-failed'), KeyboardInterrupt(), SystemExit(3)])
def test_finally_deletes_only_owned_target_after_native_failure(setup, monkeypatch, error):
    def fail(*args): raise error
    monkeypatch.setattr(launcher, 'run_native', fail)
    with pytest.raises(type(error)):
        launcher.main(setup.argv())
    stored = next(row for row in setup.events if row[0] == 'store')
    assert setup.events[-1] == ('delete', stored[1])
    assert sum(row[0] == 'delete' for row in setup.events) == 1


def test_failed_or_colliding_provision_never_launches_or_deletes_unowned_target(setup, monkeypatch):
    def fail(*args): raise ValueError('desktop_codex_test_credential_exists')
    monkeypatch.setattr(launcher, 'store_test_api_key', fail)
    with pytest.raises(ValueError, match='desktop_codex_test_credential_exists'):
        launcher.main(setup.argv())
    assert not any(row[0] in {'native', 'delete'} for row in setup.events)


def test_cleanup_failure_cannot_print_passing_launcher_result(setup, monkeypatch, capsys):
    def fail(_): raise ValueError('desktop_codex_test_credential_delete_failed')
    monkeypatch.setattr(launcher, 'delete_test_api_key', fail)
    with pytest.raises(ValueError, match='desktop_codex_test_credential_delete_failed'):
        launcher.main(setup.argv())
    assert capsys.readouterr().out == ''


@pytest.mark.parametrize('extra', [[], ['--cancel-only'], ['--memory-check']])
def test_original_scenarios_retain_flags_and_second_layout_preparation(setup, monkeypatch, extra):
    monkeypatch.setattr(launcher, 'prepare_second_layout', lambda output: setup.events.append(('second-layout', output)))
    assert launcher.main(setup.argv(extra=extra)) == 0
    native = next(row for row in setup.events if row[0] == 'native')
    env = native[5]
    assert env['INSPECTORPRO_CHAT_STREAMING'] == '0'
    assert env['INSPECTORPRO_STREAMING_AGENTS'] == 'sage'
    assert env['INSPECTORPRO_CODEX_DESKTOP_CANCEL_ONLY'] == ('1' if '--cancel-only' in extra else '0')
    assert env['INSPECTORPRO_CODEX_DESKTOP_MEMORY_CHECK'] == ('1' if '--memory-check' in extra else '0')
    assert any(row[0] == 'second-layout' for row in setup.events) == ('--memory-check' in extra)


def test_secret_file_reader_uses_explicit_file_without_interpolation_or_logging(monkeypatch, capsys):
    calls = []
    values = {'INSPECTORPRO_CODEX_API_KEY': SECRET, 'OPENAI_API_KEY': 'other-api-key'}
    def read(file, **kwargs):
        calls.append((file, kwargs))
        return values
    monkeypatch.setitem(sys.modules, 'dotenv', SimpleNamespace(dotenv_values=read))
    selected = Path('explicit-secret-file.fixture')
    assert launcher.read_test_api_key(selected) == SECRET
    assert calls == [(selected, {'interpolate': False})]
    assert values == {}
    assert SECRET not in str(capsys.readouterr())


def test_secret_file_failure_is_fixed_and_redacted(monkeypatch, capsys):
    def fail(*args, **kwargs): raise OSError(SECRET)
    monkeypatch.setitem(sys.modules, 'dotenv', SimpleNamespace(dotenv_values=fail))
    with pytest.raises(ValueError, match='^desktop_codex_test_api_key_unavailable$'):
        launcher.read_test_api_key(Path('not-opened.fixture'))
    assert SECRET not in str(capsys.readouterr())


@pytest.mark.parametrize('profile_id', ['application-check', 'normal-user', 'codex-test-short',
    'codex-test-' + 'a' * 31, 'codex-test-' + 'A' * 32, 'InspectorPro/Codex/' + TEST_ID, TEST_ID + '*'])
def test_delete_cannot_target_normal_credentials_paths_or_wildcards(monkeypatch, profile_id):
    monkeypatch.setattr(credentials, '_vault', lambda: pytest.fail('No vault access for an invalid target'))
    with pytest.raises(ValueError, match='desktop_codex_test_credential_target_invalid'):
        credentials.delete_test_api_key(profile_id)


@pytest.mark.parametrize('success,last_error,expected', [(True, 0, True), (False, 1168, False), (False, 5, None)])
def test_exact_target_delete_is_idempotent_but_does_not_hide_access_errors(monkeypatch, success, last_error, expected):
    calls = []
    def delete(*args):
        calls.append(args)
        return success
    monkeypatch.setattr(credentials, '_vault', lambda: SimpleNamespace(CredDeleteW=delete))
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: last_error, raising=False)
    if expected is None:
        with pytest.raises(ValueError, match='desktop_codex_test_credential_delete_failed'):
            credentials.delete_test_api_key(TEST_ID)
    else:
        assert credentials.delete_test_api_key(TEST_ID) is expected
    assert calls == [('InspectorPro/Codex/' + TEST_ID, 1, 0)]


def test_test_credential_collision_refuses_write_and_frees_probe(monkeypatch):
    calls = []
    monkeypatch.setattr(credentials, '_vault', lambda: SimpleNamespace(
        CredReadW=lambda *args: True, CredFree=lambda pointer: calls.append('freed')))
    monkeypatch.setattr(credentials, 'store_api_key', lambda *args: pytest.fail('Must not overwrite an existing target'))
    with pytest.raises(ValueError, match='desktop_codex_test_credential_exists'):
        credentials.store_test_api_key(TEST_ID, SECRET)
    assert calls == ['freed']


@pytest.mark.parametrize('last_error', [1168, 5])
def test_test_provision_requires_confirmed_absence(monkeypatch, last_error):
    calls = []
    monkeypatch.setattr(credentials, '_vault', lambda: SimpleNamespace(CredReadW=lambda *args: False))
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: last_error, raising=False)
    monkeypatch.setattr(credentials, 'store_api_key', lambda *args: calls.append(args))
    if last_error == 1168:
        credentials.store_test_api_key(TEST_ID, SECRET)
        assert calls == [(TEST_ID, SECRET)]
    else:
        with pytest.raises(ValueError, match='desktop_codex_test_credential_probe_failed'):
            credentials.store_test_api_key(TEST_ID, SECRET)
        assert calls == []


def test_normal_entry_and_existing_stdout_stderr_capture_are_preserved(tmp_path, monkeypatch):
    output, release, root = (tmp_path / name for name in ('output', 'release', 'checkout'))
    output.mkdir()
    release.mkdir()
    root.mkdir()
    monkeypatch.setattr(launcher, 'ROOT', root)
    args = SimpleNamespace(reliability_check=None, cancel_only=True, memory_check=False)
    save_json(output / 'codex-ui-check.json', {'status': 'passed', 'sourceUnchanged': True,
        'copyUnchanged': True, 'saveCalls': 0, 'turns': []})
    save_json(output / 'last-application-run.json', {'backends': [{'cleanup': {
        'terminationConfirmed': True, 'stdioClosed': True, 'resourcesClosed': True,
        'forced': False, 'exitCode': 0}}]})
    (output / 'codex-pilot').mkdir()
    with sqlite3.connect(output / 'codex-pilot/pilot.sqlite') as db:
        db.execute('CREATE TABLE turns (turn_id TEXT, status TEXT, result TEXT, binding TEXT, updated INTEGER)')
        db.execute('CREATE TABLE sessions (id TEXT)')
        db.execute("INSERT INTO turns VALUES ('turn', 'interrupted', '{}', 'binding', 1)")
    commands = []
    def popen(command, **kwargs):
        commands.append((command, kwargs))
        kwargs['stdout'].write(b'captured stdout\n')
        kwargs['stderr'].write(b'captured stderr\n')
        return SimpleNamespace(pid=1234, wait=lambda **kwargs: 0)
    monkeypatch.setattr(launcher.subprocess, 'Popen', popen)
    result = launcher.run_native(args, output, release, release / 'codex.exe', {})
    assert result['status'] == 'passed'
    assert (output / 'electron.stdout.log').read_bytes() == b'captured stdout\n'
    assert (output / 'electron.stderr.log').read_bytes() == b'captured stderr\n'
    command, kwargs = commands[0]
    assert command[0] == str(root / 'desktop/node_modules/electron/dist/electron.exe')
    assert command[1] == str(root / 'desktop/src/entry.cjs')
    assert kwargs['cwd'] == root
    assert json.loads((output / 'launcher.json').read_text())['status'] == 'passed'


@pytest.mark.parametrize('scenario', ['startup', 'recovery', 'editing', 'editor-change'])
def test_reliability_delegation_retains_selected_binary_load_and_scenario(tmp_path, monkeypatch, scenario):
    calls = []
    def run(*args):
        calls.append(args)
        return {'status': 'passed'}
    monkeypatch.setitem(sys.modules, 'tools.codex_desktop_reliability', SimpleNamespace(run_reliability=run))
    release, output = tmp_path / 'release', tmp_path / 'output'
    binary = release / launcher.pack.DEPS / 'codex_cli_bin/bin/codex.exe'
    args = SimpleNamespace(reliability_check=scenario, load_workers=2, affinity_cpus=4)
    env = {'SCENARIO': 'test'}
    assert launcher.run_native(args, output, release, binary, env) == {'status': 'passed'}
    command, selected_env, selected_output, selected_binary, selected_scenario, workers, cpus = calls[0]
    assert command[1] == str(launcher.ROOT / 'desktop/src/entry.cjs')
    assert (selected_env, selected_output, selected_binary, selected_scenario, workers, cpus) == (env, output, binary, scenario, 2, 4)
