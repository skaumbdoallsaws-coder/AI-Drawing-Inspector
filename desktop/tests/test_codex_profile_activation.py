import ctypes
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import pytest

from desktop.runtime import codex_config
from tools import activate_codex_desktop_profile as tool

SECRET = 'fake-api-key-never-log-' + 'x' * 40


def test_process_inventory_excludes_unrelated_codex_system_helpers(monkeypatch):
    import psutil
    def forbidden():
        pytest.fail('Unrelated protected helper must not be inspected')
    helpers = [SimpleNamespace(pid=index + 900000, info={'name': name}, oneshot=forbidden)
               for index, name in enumerate(('codex-windows-sandbox-service.exe', 'codex-code-mode-host.exe'))]
    runtime = SimpleNamespace(pid=900010, info={'name': 'codex.exe'}, oneshot=nullcontext,
                              cmdline=lambda: ['codex.exe', 'app-server'], cwd=lambda: 'runtime',
                              exe=lambda: 'codex.exe')
    monkeypatch.setattr(psutil, 'process_iter', lambda _: [*helpers, runtime])
    assert tool.process_snapshot() == [{'cmdline': ['codex.exe', 'app-server'], 'cwd': 'runtime', 'exe': 'codex.exe'}]


@pytest.mark.parametrize('name', ['codex.exe', 'python.exe', 'pythonw.exe', 'electron.exe', 'InspectorPro.exe', 'node.exe'])
def test_process_inventory_still_fails_closed_for_inaccessible_runtime(monkeypatch, name):
    import psutil
    def denied():
        raise psutil.AccessDenied(900011)
    process = SimpleNamespace(pid=900011, info={'name': name}, oneshot=nullcontext,
                              cmdline=denied)
    monkeypatch.setattr(psutil, 'process_iter', lambda _: [process])
    with pytest.raises(tool.Refused, match='desktop_process_state_unavailable'):
        tool.process_snapshot()


@pytest.mark.parametrize('outcome', ['open', 'refused', 'timeout'])
def test_listener_probe_allows_windows_refusal_delay_but_not_unknown_state(monkeypatch, outcome):
    calls = []
    def connect(address, *, timeout):
        calls.append((address, timeout))
        if outcome == 'refused':
            raise ConnectionRefusedError()
        if outcome == 'timeout':
            raise TimeoutError()
        return nullcontext()
    monkeypatch.setattr(tool.socket, 'create_connection', connect)
    if outcome == 'timeout':
        with pytest.raises(tool.Refused, match='desktop_listener_state_unavailable'):
            tool.listener_open('http://127.0.0.1:8480')
    else:
        assert tool.listener_open('http://127.0.0.1:8480') is (outcome == 'open')
    assert calls == [(('127.0.0.1', 8480), 5)]


def save(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_bytes(tool.canonical(value))


@pytest.fixture
def case(tmp_path, monkeypatch):
    root, release, data, facility, library = (tmp_path / name for name in ('app', 'bundle', 'data', 'facility', 'library'))
    for folder in (root, data, facility, library):
        folder.mkdir()
    for name in ('server.py', 'desktop/src/entry.cjs', 'static/index.html'):
        file = root / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('reviewed code', encoding='utf-8')
    deps = root / tool.pack.DEPS
    binary = deps / 'codex_cli_bin/bin/codex.exe'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fake binary, never executed')
    for name, version in codex_config.PINS.items():
        info = deps / (name.replace('-', '_') + '-' + version + '.dist-info')
        info.mkdir()
        (info / 'METADATA').write_text(f'Name: {name}\nVersion: {version}\n', encoding='utf-8')
    prepared = tool.pack.prepare_bundle(root, release, deps, probe=lambda _: None)
    monkeypatch.setattr(tool, 'ROOT', root)
    gateway = root / '.runtime/gateway'
    (gateway / 'litellm').mkdir(parents=True)
    (gateway / 'litellm/__init__.py').write_text('# gateway fixture', encoding='utf-8')
    (gateway / 'gateway.json').write_text('{}', encoding='utf-8')
    profile = dict(schemaVersion=1, mode='application', profileId='normal-existing-profile',
        origin='http://127.0.0.1:8480', dataRoot=str(data), facilityRoot=str(facility), libraryRoot=str(library),
        backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()), startupLayoutId='fl-existing',
        modelGateway={'configPath': str(gateway / 'gateway.json'), 'dependencyRoot': str(gateway)})
    profile_file = root / '.runtime/desktop-native/application-profile.json'
    profile_file.parent.mkdir(parents=True)
    original = (json.dumps(profile, indent=3) + '\r\n').encode('utf-8')
    profile_file.write_bytes(original)
    layout = facility / 'manual-layout.json'
    layout.write_bytes(b'user manual layout, untouched')
    output = root / '.runtime/native-evidence'
    files = tool.application_code_files(root)
    evidence = {'schemaVersion': 1, 'status': 'verified', 'appRoot': str(root), 'releaseRoot': str(release),
        'packageSha256': prepared['packageSha256'], 'before': files, 'after': files,
        'beforeSha256': tool.sha_bytes(tool.canonical(files)), 'afterSha256': tool.sha_bytes(tool.canonical(files)),
        'applicationCodeUnchanged': True, 'dependencyBundleUnchanged': True}
    evidence_file = output / 'application-code-evidence.json'
    save(evidence_file, evidence)
    report_file = output / 'codex-desktop-acceptance.json'
    report = {'status': 'passed', 'scenario': 'editing', 'applicationCodeEvidence': str(evidence_file)}
    save(report_file, report)
    options = dict(app_root=root, release=release, profile_file=profile_file, backup=tmp_path / 'rollback',
        package_sha256=prepared['packageSha256'], profile_sha256=tool.sha_bytes(original),
        acceptances=[(report_file, tool.pack.digest(report_file), tool.pack.digest(evidence_file))], edit_previews=True)
    calls = []
    monkeypatch.setattr(tool, 'credential_exists', lambda _: calls.append('probe') or True)
    monkeypatch.setattr(tool.credentials, 'read_api_key', lambda _: calls.append('read-existing') or SECRET)
    monkeypatch.setattr(tool.credentials, 'store_api_key', lambda *args: calls.append(('store', *args)))
    monkeypatch.setattr(tool, 'read_key_file', lambda _: calls.append('read-file') or SECRET)
    monkeypatch.setattr(tool, 'process_snapshot', lambda: pytest.fail('Real process enumeration forbidden in tests'))
    monkeypatch.setattr(tool, 'listener_open', lambda _: pytest.fail('Real listener probe forbidden in tests'))
    def apply(**overrides):
        args = dict(options, apply=True, stopped=True, allow_paid=True, processes=lambda: [], listener=lambda _: False)
        args.update(overrides)
        return tool.activate(**args)
    def rollback(**overrides):
        args = dict(record_file=options['backup'] / tool.RECORD,
            record_sha256=tool.pack.digest(options['backup'] / tool.RECORD), profile_file=profile_file,
            app_root=root, apply=True, stopped=True, processes=lambda: [], listener=lambda _: False)
        args.update(overrides)
        return tool.rollback(**args)
    return SimpleNamespace(root=root, release=release, profile=profile, file=profile_file, original=original,
        layout=layout, evidence=evidence, evidence_file=evidence_file, report=report, report_file=report_file,
        options=options, calls=calls, apply=apply, rollback=rollback)


def test_dry_run_never_reads_key_file_vault_or_writes_backup(case):
    result = tool.activate(**case.options, provision=True, key_file=case.root / '.env')
    assert result['status'] == 'planned' and case.calls == []
    assert case.file.read_bytes() == case.original
    assert not case.options['backup'].exists()


@pytest.mark.parametrize('stale_scenario', [None, 'recovery'])
def test_final_multi_scenario_set_requires_same_current_code_hash(case, stale_scenario):
    acceptances = []
    for scenario in ('editing', 'editor-change', 'recovery', 'startup', 'memory'):
        output = case.root / '.runtime' / ('final-' + scenario)
        evidence_file = output / 'application-code-evidence.json'
        evidence = dict(case.evidence)
        if scenario == stale_scenario:
            evidence['beforeSha256'] = evidence['afterSha256'] = '0' * 64
        save(evidence_file, evidence)
        report_file = output / 'codex-desktop-acceptance.json'
        report = {'status': 'passed', 'applicationCodeEvidence': str(evidence_file)}
        if scenario == 'memory':
            report['memoryCheck'] = True  # The existing non-reliability launcher shape.
        else:
            report['scenario'] = scenario
        save(report_file, report)
        acceptances.append((report_file, tool.pack.digest(report_file), tool.pack.digest(evidence_file)))
    if stale_scenario:
        with pytest.raises(tool.Refused, match='native_evidence_or_application_code_changed'):
            case.apply(acceptances=acceptances)
        assert case.calls == [] and case.file.read_bytes() == case.original
    else:
        result = case.apply(acceptances=acceptances)
        record = tool.read_json(Path(result['rollbackRecord']))
        assert [item['scenario'] for item in record['acceptances']] == ['editing', 'editor-change', 'recovery', 'startup', 'memory']
        assert record['applicationCodeSha256'] == case.evidence['afterSha256']
        assert case.rollback()['status'] == 'rolled-back'


def test_activate_only_adds_codex_runtime_preserves_gateway_stores_and_exact_rollback(case, capsys):
    before_code = tool.application_code_files(case.root)
    result = case.apply()
    assert result['status'] == 'activated' and result['credentialAction'] == 'reused'
    profile = json.loads(case.file.read_bytes())
    assert {k: v for k, v in profile.items() if k != 'codexRuntime'} == case.profile
    assert profile['codexRuntime']['pilotRoot'] == str(Path(case.profile['dataRoot']) / 'codex-pilot')
    assert profile['codexRuntime']['packageSha256'] == case.options['package_sha256']
    assert (case.options['backup'] / 'profile.before.json').read_bytes() == case.original
    assert case.calls == ['probe', 'read-existing']
    assert case.rollback(apply=False)['status'] == 'rollback-planned'
    assert case.rollback()['status'] == 'rolled-back'
    assert case.file.read_bytes() == case.original
    assert case.rollback()['status'] == 'rolled-back'
    assert case.calls == ['probe', 'read-existing']  # Neither rollback touches vault.
    assert case.layout.read_bytes() == b'user manual layout, untouched'
    assert tool.application_code_files(case.root) == before_code
    for file in case.options['backup'].iterdir():
        assert SECRET.encode() not in file.read_bytes()
    assert SECRET not in str(capsys.readouterr())


@pytest.mark.parametrize('field', ['status', 'hash', 'code', 'bundle', 'evidence-hash', 'binding', 'editing-gate'])
def test_unapproved_or_changed_evidence_refuses_before_vault_or_profile_writes(case, field):
    if field == 'status':
        case.report['status'] = 'failed'
        save(case.report_file, case.report)
        case.options['acceptances'][0] = (case.report_file, tool.pack.digest(case.report_file), tool.pack.digest(case.evidence_file))
    elif field == 'hash':
        case.options['package_sha256'] = '0' * 64
    elif field == 'code':
        (case.root / 'static/index.html').write_text('changed code', encoding='utf-8')
    elif field == 'bundle':
        (case.release / tool.pack.DEPS / 'extra.py').write_text('changed dependency', encoding='utf-8')
    elif field == 'evidence-hash':
        case.options['acceptances'][0] = (case.report_file, tool.pack.digest(case.report_file), '0' * 64)
    elif field == 'binding':
        case.evidence['appRoot'] = str(case.release)
        save(case.evidence_file, case.evidence)
        case.options['acceptances'][0] = (case.report_file, tool.pack.digest(case.report_file), tool.pack.digest(case.evidence_file))
    elif field == 'editing-gate':
        case.report['scenario'] = 'editor-change'
        save(case.report_file, case.report)
        case.options['acceptances'][0] = (case.report_file, tool.pack.digest(case.report_file), tool.pack.digest(case.evidence_file))
    with pytest.raises(ValueError):
        case.apply()
    assert case.calls == [] and case.file.read_bytes() == case.original
    assert not case.options['backup'].exists()


@pytest.mark.parametrize('override', [{'stopped': False}, {'allow_paid': False}, {'listener': lambda _: True},
    {'processes': lambda: [{'cmdline': [], 'cwd': None, 'exe': None}]}])
def test_required_approvals_and_stopped_checks_fail_before_vault_or_backup(case, override):
    with pytest.raises(tool.Refused):
        case.apply(**override)
    assert case.calls == [] and not case.options['backup'].exists()


@pytest.mark.parametrize('kind', ['electron', 'python', 'codex'])
def test_running_application_backend_or_selected_codex_refuses(case, kind):
    exe = str((case.release if kind == 'codex' else case.root) / (kind + '.exe'))
    with pytest.raises(tool.Refused, match='desktop_or_backend_still_running'):
        case.apply(processes=lambda: [{'cmdline': [exe], 'cwd': str(case.root), 'exe': exe}])
    assert case.calls == []


def test_unrelated_codex_authoring_session_is_not_an_application_backend(case):
    tool.assert_stopped(case.profile, case.file, case.root, case.release, stopped=True,
        processes=lambda: [{'cmdline': ['codex.exe'], 'cwd': str(case.root),
                            'exe': str(case.root.parent / 'other-codex/codex.exe')}], listener=lambda _: False)


def test_existing_credential_requires_separate_replace_approval_before_key_file_read(case):
    with pytest.raises(tool.Refused, match='existing_credential_replacement_not_authorized'):
        case.apply(provision=True, key_file=case.root / '.env')
    assert case.calls == ['probe'] and case.file.read_bytes() == case.original
    assert (case.options['backup'] / tool.RECORD).is_file()


@pytest.mark.parametrize('exists', [False, True])
def test_explicit_provision_and_replace_use_only_profile_scoped_vault_and_no_secret_files(case, monkeypatch, exists):
    monkeypatch.setattr(tool, 'credential_exists', lambda _: exists)
    result = case.apply(provision=True, replace=exists, key_file=case.root / '.env')
    assert result['credentialAction'] == ('replaced' if exists else 'provisioned')
    assert case.calls == ['read-file', ('store', case.profile['profileId'], SECRET)]
    assert SECRET not in json.dumps(result)
    for file in case.options['backup'].iterdir():
        assert SECRET.encode() not in file.read_bytes()
    case.rollback()
    assert case.calls == ['read-file', ('store', case.profile['profileId'], SECRET)]


def test_missing_credential_without_opt_in_cannot_activate(case, monkeypatch):
    monkeypatch.setattr(tool, 'credential_exists', lambda _: False)
    with pytest.raises(tool.Refused, match='existing_credential_or_explicit_provision_required'):
        case.apply()
    assert case.calls == [] and case.file.read_bytes() == case.original


def test_credential_appearing_after_probe_is_not_overwritten(case, monkeypatch):
    values = iter([False, True])
    monkeypatch.setattr(tool, 'credential_exists', lambda _: next(values))
    with pytest.raises(tool.Refused, match='credential_appeared_before_provision'):
        case.apply(provision=True, key_file=case.root / '.env')
    assert case.calls == ['read-file'] and case.file.read_bytes() == case.original


@pytest.mark.parametrize('after_write', [False, True])
def test_failed_atomic_install_restores_profile_and_keeps_rollback_record(case, after_write):
    def failing(file, content):
        if after_write:
            tool.pack.atomic_bytes(file, content)
        raise OSError(SECRET)
    with pytest.raises(tool.Refused, match='activation_failed_profile_restored'):
        case.apply(writer=failing)
    assert case.file.read_bytes() == case.original
    assert (case.options['backup'] / tool.RECORD).is_file()
    assert case.rollback()['status'] == 'rolled-back'


def test_failure_never_reverts_concurrent_user_profile_edit(case):
    def failing(file, content):
        file.write_bytes(b'later-user-change')
        raise OSError('failed')
    with pytest.raises(tool.Refused, match='activation_failed_with_profile_conflict'):
        case.apply(writer=failing)
    assert case.file.read_bytes() == b'later-user-change'


@pytest.mark.parametrize('target', ['profile', 'backup', 'record'])
def test_rollback_refuses_conflicts_without_vault_access_or_overwrites(case, target):
    result = case.apply()
    file = {'profile': case.file, 'backup': case.options['backup'] / 'profile.before.json',
            'record': case.options['backup'] / tool.RECORD}[target]
    file.write_bytes(b'changed by user')
    with pytest.raises(ValueError):
        case.rollback(record_sha256=result['rollbackRecordSha256'])
    assert file.read_bytes() == b'changed by user'
    assert case.calls == ['probe', 'read-existing']


def test_rollback_requires_same_profile_and_stopped_precondition(case):
    case.apply()
    with pytest.raises(tool.Refused):
        case.rollback(profile_file=case.root / 'another-profile.json')
    with pytest.raises(tool.Refused, match='explicit_desktop_stopped_precondition_required'):
        case.rollback(stopped=False)


def test_rollback_does_not_require_bundle_to_still_verify(case):
    case.apply()
    (case.release / tool.pack.DEPS / 'extra.py').write_text('bad dependency', encoding='utf-8')
    assert case.rollback()['status'] == 'rolled-back'
    assert case.file.read_bytes() == case.original


def test_backup_cannot_overlap_app_source_or_existing_user_stores(case):
    for backup in (case.root / 'new-backup', Path(case.profile['facilityRoot']) / 'backup', case.release / 'backup'):
        with pytest.raises(ValueError):
            case.apply(backup=backup)
    assert case.calls == []


def test_existing_runtime_is_not_reconfigured_by_add_only_tool(case):
    case.apply()
    options = dict(case.options, backup=case.root.parent / 'new-backup', profile_sha256=tool.pack.digest(case.file))
    with pytest.raises(tool.Refused, match='profile_already_has_codex_runtime'):
        tool.activate(**options)


def test_source_changed_during_vault_step_prevents_profile_activation(case, monkeypatch):
    def read(_):
        (case.root / 'server.py').write_text('late source change', encoding='utf-8')
        return SECRET
    monkeypatch.setattr(tool.credentials, 'read_api_key', read)
    with pytest.raises(tool.Refused, match='native_evidence_or_application_code_changed'):
        case.apply()
    assert case.file.read_bytes() == case.original


def test_late_profile_change_is_rechecked_after_final_process_guard(case):
    calls = 0
    def processes():
        nonlocal calls
        calls += 1
        if calls == 3:
            case.file.write_bytes(b'late manual profile edit')
        return []
    with pytest.raises(tool.Refused, match='approved_file_changed'):
        case.apply(processes=processes)
    assert case.file.read_bytes() == b'late manual profile edit'


def test_existing_transaction_lock_is_not_removed(case):
    lock = case.file.with_name(case.file.name + '.codex-activation.lock')
    lock.write_bytes(b'other transaction')
    with pytest.raises(FileExistsError):
        case.apply()
    assert lock.read_bytes() == b'other transaction' and case.calls == []


def test_cli_does_not_echo_arbitrary_exception_or_cli_key(monkeypatch, capsys):
    def fail(**_):
        raise OSError(SECRET)
    monkeypatch.setattr(tool, 'activate', fail)
    args = ['activate', '--release', 'fake', '--backup', 'fake', '--profile-file', 'fake',
            '--package-sha256', 'a' * 64, '--profile-sha256', 'b' * 64,
            '--acceptance', 'fake', 'c' * 64, 'd' * 64]
    assert tool.main(args) == 1
    assert SECRET not in str(capsys.readouterr())
    with pytest.raises(SystemExit):
        tool.main(args + ['--api-key', SECRET])
    assert SECRET not in str(capsys.readouterr())


def test_key_file_reader_is_explicit_noninterpolating_and_clears_values(tmp_path, monkeypatch):
    calls = []
    values = {'INSPECTORPRO_CODEX_API_KEY': SECRET}
    def read(file, **kwargs):
        calls.append((file, kwargs))
        return values
    monkeypatch.setitem(sys.modules, 'dotenv', SimpleNamespace(dotenv_values=read))
    file = tmp_path / '.env'
    assert tool.read_key_file(file) == SECRET
    assert calls == [(file, {'interpolate': False})] and values == {}


@pytest.mark.parametrize('error,expected', [(1168, False), (5, None)])
def test_vault_presence_distinguishes_absent_from_inaccessible(monkeypatch, error, expected):
    calls = []
    monkeypatch.setattr(tool.credentials, '_vault', lambda: SimpleNamespace(
        CredReadW=lambda *args: calls.append(args[:3]) or False))
    monkeypatch.setattr(ctypes, 'get_last_error', lambda: error, raising=False)
    if expected is None:
        with pytest.raises(tool.Refused, match='credential_presence_unavailable'):
            tool.credential_exists('normal-profile')
    else:
        assert tool.credential_exists('normal-profile') is expected
    assert calls == [('InspectorPro/Codex/normal-profile', 1, 0)]


def test_vault_presence_frees_and_zeroes_exact_scoped_probe(monkeypatch):
    blob = (ctypes.c_ubyte * len(SECRET))(*SECRET.encode('ascii'))
    item = tool.credentials.Credential(Type=1, CredentialBlobSize=len(blob), CredentialBlob=blob)
    pointer = ctypes.pointer(item)
    calls = []
    def read(target, kind, flags, output):
        calls.append((target, kind, flags))
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(tool.credentials.Credential)))[0] = pointer
        return True
    def free(_):
        assert bytes(blob) == bytes(len(SECRET))
        calls.append('freed')
    monkeypatch.setattr(tool.credentials, '_vault', lambda: SimpleNamespace(CredReadW=read, CredFree=free))
    assert tool.credential_exists('normal-profile') is True
    assert calls == [('InspectorPro/Codex/normal-profile', 1, 0), 'freed']
