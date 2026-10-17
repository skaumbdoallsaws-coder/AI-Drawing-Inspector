import ctypes
import io
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import uuid

import pytest

from desktop.runtime import codex_config as config
from desktop.runtime import codex_credentials as credentials
from desktop.runtime.application_profile import ApplicationProfile, load_application_profile
from desktop.runtime.codex_credentials import credential_target, validate_key
from tools import codex_desktop_pack as pack


def write_json(file, value):
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(json.dumps(value), encoding='utf-8')


@pytest.fixture
def deployment(tmp_path, monkeypatch):
    source, release, build = (tmp_path / name for name in ('source', 'release', 'build'))
    source.mkdir()
    (source / 'server.py').write_text('# old source\n', encoding='utf-8')
    for name in ('static/index.html', 'ai_inspector/__init__.py'):
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text('fixture', encoding='utf-8')
    (source / '.env').write_text('must-not-be-read', encoding='utf-8')
    dependencies = source / pack.DEPS
    binary = dependencies / 'codex_cli_bin/bin/codex.exe'
    binary.parent.mkdir(parents=True)
    binary.write_bytes(b'fake-binary-no-inference')
    for name, version in config.PINS.items():
        info = dependencies / (name.replace('-', '_') + '-' + version + '.dist-info')
        info.mkdir()
        (info / 'METADATA').write_text(f'Name: {name}\nVersion: {version}\n', encoding='utf-8')
    helper = pack.snapshot_helper()
    monkeypatch.setattr(helper, 'git_inventory', lambda _: ('a' * 40, set()))
    monkeypatch.setattr(pack, 'snapshot_helper', lambda: helper)
    original_read = Path.read_bytes
    def guarded_read(file):
        assert not file.name.startswith('.env'), 'Deployment must never read dotenv files'
        return original_read(file)
    monkeypatch.setattr(Path, 'read_bytes', guarded_read)
    helper.prepare_snapshot(source, build)
    (build / '.env').write_text('existing-never-read', encoding='utf-8')
    (build / 'unrelated.txt').write_text('user change', encoding='utf-8')
    (source / 'server.py').write_text('# validated new source\n', encoding='utf-8')
    pack.prepare(source, release, dependencies, probe=lambda _: None)
    data, facility, library = (tmp_path / name for name in ('data', 'facility', 'library'))
    for folder in (data, facility, library):
        folder.mkdir()
    layout = facility / 'layout.json'
    layout.write_bytes(b'original-layout-data')
    profile = dict(schemaVersion=1, mode='application', profileId='pack-test', origin='http://127.0.0.1:8480',
                   dataRoot=str(data), facilityRoot=str(facility), libraryRoot=str(library),
                   backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()), startupLayoutId='fl-test')
    profile_file = tmp_path / 'profile.json'
    write_json(profile_file, profile)
    args = [release, build, profile_file, tmp_path / 'backup']
    return SimpleNamespace(source=source, release=release, build=build, profile=profile, file=profile_file,
                           backup=args[-1], args=args, layout=layout)


def runtime_profile(f):
    value = dict(f.profile, codexRuntime={
        'schemaVersion': 1, 'model': 'gpt-5.5', 'editPreviews': True, 'allowPaidInference': True,
        'dependencyRoot': str(f.release / pack.DEPS),
        'packageSha256': config.digest(f.release / pack.DEPS / config.PACKAGE),
        'binary': str(f.release / pack.DEPS / 'codex_cli_bin/bin/codex.exe'),
        'pilotRoot': str(Path(f.profile['dataRoot']) / 'codex-pilot'),
        'credentialTarget': credential_target(f.profile['profileId'])})
    return ApplicationProfile(value)


def test_prepare_preserves_snapshot_and_full_dependency_inventory(deployment):
    f = deployment
    result = pack.verify_release(f.release)
    assert result['pins'] == config.PINS
    assert result['model'] == 'gpt-5.5'
    assert not (f.release / '.env').exists()
    assert not (f.release / '.runtime/facility-layout').exists()
    package = pack.read_json(f.release / pack.DEPS / config.PACKAGE)
    assert package['versions'] == config.PINS
    assert package['pythonTag'] == sys.implementation.cache_tag


@pytest.mark.parametrize('field,value', [
    ('apiKey', 'never-store-this-key'), ('authMode', 'chatgpt'), ('model', 'other'),
    ('allowPaidInference', False), ('allowPaidInference', 1), ('editPreviews', 1),
    ('credentialTarget', 'another-profile'), ('schemaVersion', True),
    ('packageSha256', 'bad'), ('packageSha256', None),
    ('binary', 'relative.exe'), ('dependencyRoot', 'relative'), ('pilotRoot', 'relative'),
])
def test_config_rejects_unbounded_or_secret_fields(deployment, field, value):
    profile = runtime_profile(deployment)
    profile.value['codexRuntime'][field] = value
    with pytest.raises(ValueError, match='^desktop_codex_config_invalid$'):
        config.validate_config(profile.value['codexRuntime'], profile.value)


def test_config_preserves_partition_identity_and_rejects_layout_overlap(deployment):
    f = deployment
    original = load_application_profile(f.file)
    enabled = runtime_profile(f)
    write_json(f.file, enabled.value)
    assert load_application_profile(f.file).store_binding == original.store_binding
    enabled.value['codexRuntime']['pilotRoot'] = f.profile['facilityRoot']
    with pytest.raises(ValueError):
        config.validate_config(enabled.value['codexRuntime'], enabled.value)


def test_disabled_environment_masks_inherited_and_dotenv_activation(deployment):
    env = {'INSPECTORPRO_CODEX_API_KEY': 'inherited', 'inspectorpro_codex_readonly_pilot': '1',
           'CODEX_HOME': 'personal', 'INSPECTORPRO_CODEX_UNKNOWN': 'unsafe', 'OPENAI_API_KEY': 'legacy-only'}
    config.configure_codex(ApplicationProfile(deployment.profile), deployment.build, environment=env,
                           credential_reader=lambda _: pytest.fail('Vault must not be read when disabled'))
    assert env['INSPECTORPRO_CODEX_READONLY_PILOT'] == '0'
    assert env['INSPECTORPRO_CODEX_EDIT_PREVIEWS'] == '0'
    assert env['INSPECTORPRO_CODEX_API_KEY'] == ''
    assert 'CODEX_HOME' not in env
    assert 'INSPECTORPRO_CODEX_UNKNOWN' not in env
    assert env['OPENAI_API_KEY'] == 'legacy-only'


def test_enabled_environment_is_backend_only_and_deps_append(deployment):
    profile = runtime_profile(deployment)
    secret = 'test-only-dedicated-api-key-' + 'x' * 32
    env = {'INSPECTORPRO_CODEX_MODEL': 'wrong', 'INSPECTORPRO_CODEX_API_KEY': 'wrong', 'CODEX_HOME': 'personal'}
    original_path = sys.path[:]
    try:
        config.configure_codex(profile, deployment.release, environment=env,
                               credential_reader=lambda _: secret, protect_output=False)
        assert sys.path[:len(original_path)] == original_path
        assert sys.path[-1] == profile.value['codexRuntime']['dependencyRoot']
    finally:
        sys.path[:] = original_path
    assert env['INSPECTORPRO_CODEX_MODEL'] == 'gpt-5.5'
    assert env['INSPECTORPRO_CODEX_API_KEY'] == secret
    assert env['INSPECTORPRO_CODEX_EDIT_PREVIEWS'] == '1'
    assert env['INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE'] == '1'
    assert secret not in json.dumps(profile.value)


def test_subscription_profile_never_reads_or_passes_api_credential(deployment):
    profile = runtime_profile(deployment)
    profile.value['codexRuntime'].update(schemaVersion=2, authMode='chatgpt_plan', model='gpt-6.1-sol',
        allowPaidInference=False, credentialTarget='InspectorPro/ChatGPT/' + profile.value['profileId'])
    env = {'INSPECTORPRO_CODEX_API_KEY': 'must-not-inherit'}
    config.configure_codex(profile, deployment.release, environment=env, add_site=lambda _: None,
        credential_reader=lambda _: pytest.fail('Subscription mode must not read the API vault'), protect_output=False)
    assert env['INSPECTORPRO_CODEX_API_KEY'] == ''
    assert env['INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE'] == '0'
    assert env['INSPECTORPRO_CODEX_ALLOW_SUBSCRIPTION_INFERENCE'] == '1'
    assert env['INSPECTORPRO_CODEX_AUTH_ROOT'] == str(Path(profile.value['dataRoot']) / 'chatgpt-auth')
    assert env['INSPECTORPRO_CODEX_MODEL'] == 'gpt-6.1-sol'
    assert 'ACCESS_TOKEN' not in json.dumps(env)
    profile.value['codexRuntime']['allowPaidInference'] = True
    with pytest.raises(ValueError, match='desktop_codex_config_invalid'):
        config.validate_config(profile.value['codexRuntime'], profile.value)


def test_missing_vault_key_has_fixed_error_and_never_uses_provider_key(deployment, capsys):
    secret = 'test-only-never-log-' + 'x' * 32
    def fail(_): raise RuntimeError(secret)
    env = {'OPENAI_API_KEY': secret}
    with pytest.raises(ValueError, match='^desktop_codex_credential_unavailable$'):
        config.configure_codex(runtime_profile(deployment), deployment.release, environment=env,
                               credential_reader=fail, protect_output=False)
    assert env['INSPECTORPRO_CODEX_API_KEY'] == ''
    assert env['INSPECTORPRO_CODEX_READONLY_PILOT'] == '0'
    assert secret not in str(capsys.readouterr())


def test_output_redacts_key_at_every_write_boundary():
    secret = 'test-only-secret-' + 'a' * 32
    for split in range(len(secret) + 1):
        output = io.StringIO()
        stream = config.RedactingStream(output, secret)
        stream.write('before ' + secret[:split])
        stream.flush()
        stream.write(secret[split:] + ' after\n')
        stream.flush()
        assert output.getvalue() == 'before [redacted] after\n'
        assert secret not in output.getvalue()
    output = io.StringIO()
    stream = config.RedactingStream(output, secret)
    stream.write(secret[:10])
    stream.flush()
    assert output.getvalue() == ''


def test_key_validation_never_echoes_invalid_input():
    for value in ('short', 'a' * 31, 'a' * 2049, 'test-secret\n' * 10):
        with pytest.raises(ValueError, match='^desktop_codex_credential_invalid$'):
            validate_key(value)


def test_runtime_accepts_normal_checkout_external_bundle_and_rejects_tampered_binary(deployment):
    f = deployment
    profile = runtime_profile(f)
    assert not (f.source / 'desktop-checkpoint.json').exists()
    config.validate_package(profile.value['codexRuntime'], f.source)
    Path(profile.value['codexRuntime']['binary']).write_bytes(b'changed-binary')
    with pytest.raises(ValueError, match='desktop_codex_package_invalid'):
        config.validate_package(profile.value['codexRuntime'], f.release)
    with pytest.raises(ValueError):
        pack.verify_release(f.release)


def test_dependency_only_bundle_preserves_normal_source_resources_and_stores(deployment):
    f = deployment
    generated = f.source / 'generated/industrial_assets/local_library/catalog.json'
    write_json(generated, {'manual-content': 'not copied'})
    bundle = f.source.parent / 'dependency-bundle'
    before = config.digest(f.source / 'server.py')
    result = pack.prepare_bundle(f.source, bundle, f.source / pack.DEPS, probe=lambda _: None)
    assert result['status'] == 'prepared'
    assert not (bundle / 'server.py').exists() and not (bundle / 'generated').exists()
    assert not (bundle / 'desktop-checkpoint.json').exists()
    assert config.digest(f.source / 'server.py') == before
    assert json.loads(generated.read_text()) == {'manual-content': 'not copied'}
    profile = runtime_profile(f)
    profile.value['codexRuntime'].update(dependencyRoot=str(bundle / pack.DEPS),
        binary=str(bundle / pack.DEPS / 'codex_cli_bin/bin/codex.exe'), packageSha256=result['packageSha256'])
    config.validate_config(profile.value['codexRuntime'], profile.value)
    config.configure_codex(profile, f.source, environment={}, credential_reader=lambda _: 'test-key-' + 'x' * 40,
                           add_site=lambda _: None, protect_output=False)
    assert pack.verify_bundle(bundle)['packageSha256'] == result['packageSha256']
    with pytest.raises(ValueError, match='desktop_codex_new_bundle_required'):
        pack.prepare_bundle(f.source, bundle, f.source / pack.DEPS, probe=lambda _: None)
    assert f.layout.read_bytes() == b'original-layout-data'


@pytest.mark.parametrize('change', ['module', 'extra', 'cache', 'manifest-and-module', 'metadata'])
def test_runtime_verifies_entire_dependency_tree_and_pinned_manifest(deployment, change):
    f = deployment
    profile = runtime_profile(f)
    dependencies = f.release / pack.DEPS
    if change in {'module', 'extra', 'manifest-and-module'}:
        (dependencies / 'changed.py').write_text('# unreviewed code', encoding='utf-8')
    if change == 'cache':
        (dependencies / '__pycache__').mkdir()
        (dependencies / '__pycache__/unreviewed.pyc').write_bytes(b'not trusted')
    if change == 'manifest-and-module':
        package = pack.read_json(dependencies / config.PACKAGE)
        package['files'] = pack.dependency_files(dependencies)
        write_json(dependencies / config.PACKAGE, package)
    if change == 'metadata':
        (dependencies / 'mcp-2.3.0.dist-info/METADATA').write_text('Name: mcp\nVersion: 2.4.0\n', encoding='utf-8')
    calls = []
    with pytest.raises(ValueError, match='desktop_codex_'):
        config.configure_codex(profile, f.source, environment={},
                               credential_reader=lambda _: calls.append('vault'), add_site=lambda _: calls.append('site'))
    assert calls == []


def test_normal_checkout_cannot_use_mutable_in_tree_dependencies(deployment):
    f = deployment
    profile = runtime_profile(f)
    profile.value['codexRuntime'].update(dependencyRoot=str(f.source / pack.DEPS),
        binary=str(f.source / pack.DEPS / 'codex_cli_bin/bin/codex.exe'))
    with pytest.raises(ValueError, match='desktop_codex_dependency_source_overlap'):
        config.validate_package(profile.value['codexRuntime'], f.source)
    with pytest.raises(ValueError, match='desktop_codex_paths_overlap'):
        pack.prepare_bundle(f.source, f.source / 'bundle', f.source / pack.DEPS, probe=lambda _: None)


def test_dependency_walk_checks_shared_ancestors_per_directory(tmp_path, monkeypatch):
    root = tmp_path / 'dependencies'
    nested = root / 'package'
    nested.mkdir(parents=True)
    for index in range(20):
        (nested / f'module{index}.py').write_bytes(b'# verified source')
    calls = []
    original = config.local_path
    def observed(path):
        calls.append(Path(path))
        return original(path)
    monkeypatch.setattr(config, 'local_path', observed)
    inventory = config.dependency_files(root)
    assert len(inventory) == 20
    assert len(calls) == 3  # Root binding and the two visited directories.
    assert all(row['sha256'] == config.digest(nested / Path(row['path']).name) for row in inventory)


@pytest.mark.parametrize('kind', ['file-symlink', 'directory-symlink', 'directory-junction'])
def test_dependency_walk_rejects_child_links_before_reading(tmp_path, monkeypatch, kind):
    root = tmp_path / 'dependencies'
    root.mkdir()
    child = root / 'untrusted'
    if kind.startswith('directory'):
        child.mkdir()
    else:
        child.write_bytes(b'untrusted')
    method = 'is_junction' if kind.endswith('junction') else 'is_symlink'
    original = getattr(Path, method, lambda _: False)
    monkeypatch.setattr(Path, method, lambda path: path == child or original(path), raising=False)
    monkeypatch.setattr(config, 'digest', lambda _: pytest.fail('Linked content must not be read'))
    with pytest.raises(ValueError, match='desktop_codex_dependency_link_refused'):
        config.dependency_files(root)


def test_promotion_and_rollback_are_dry_runs_by_default(deployment):
    f = deployment
    before = f.file.read_bytes()
    assert pack.promote(*f.args, allow_paid=True)['status'] == 'planned'
    assert not f.backup.exists()
    assert f.file.read_bytes() == before
    with pytest.raises(ValueError):
        pack.promote(*f.args, apply=True, allow_paid=True)
    with pytest.raises(ValueError):
        pack.promote(*f.args)
    with pytest.raises(ValueError, match='desktop_codex_approved_release_hash_required'):
        pack.promote(*f.args, apply=True, desktop_stopped=True, allow_paid=True, expected_sha256='wrong')
    assert not f.backup.exists()


def test_promotion_rollback_preserve_layout_identity_and_unrelated_changes(deployment):
    f = deployment
    before = f.file.read_bytes()
    old_code = (f.build / 'server.py').read_bytes()
    assert pack.promote(*f.args, apply=True, desktop_stopped=True, allow_paid=True, edit_previews=True,
                        expected_sha256=config.digest(f.release / pack.RELEASE))['status'] == 'promoted'
    profile = load_application_profile(f.file)
    assert profile.value['codexRuntime']['editPreviews'] is True
    assert profile.value['facilityRoot'] == f.profile['facilityRoot']
    assert profile.value['backendId'] == f.profile['backendId']
    config.validate_package(profile.value['codexRuntime'], f.build)
    assert f.layout.read_bytes() == b'original-layout-data'
    assert (f.build / 'unrelated.txt').read_text() == 'user change'
    assert pack.rollback(f.backup)['status'] == 'rollback-planned'
    assert (f.build / 'server.py').read_bytes() != old_code
    assert pack.rollback(f.backup, apply=True, desktop_stopped=True)['status'] == 'rolled-back'
    assert f.file.read_bytes() == before
    assert (f.build / 'server.py').read_bytes() == old_code
    assert not (f.build / pack.DEPS / 'codex_cli_bin/bin/codex.exe').exists()
    assert (f.build / '.env').exists()
    assert (f.build / 'unrelated.txt').read_text() == 'user change'
    assert f.layout.read_bytes() == b'original-layout-data'
    assert pack.rollback(f.backup, apply=True, desktop_stopped=True)['status'] == 'rolled-back'


def test_failed_install_rolls_back_before_enabling_profile(deployment):
    f = deployment
    before = f.file.read_bytes()
    writes = 0
    def fail_during_install(file, content):
        nonlocal writes
        writes += 1
        if writes == 4: raise OSError('injected write failure')
        pack.atomic_bytes(file, content)
    with pytest.raises(ValueError, match='desktop_codex_promotion_failed_rolled_back'):
        pack.promote(*f.args, apply=True, desktop_stopped=True, allow_paid=True, writer=fail_during_install,
                     expected_sha256=config.digest(f.release / pack.RELEASE))
    assert f.file.read_bytes() == before
    assert (f.build / 'server.py').read_text() == '# old source\n'
    assert f.layout.read_bytes() == b'original-layout-data'
    assert pack.read_json(f.backup / pack.JOURNAL)['status'] == 'rolled-back'


@pytest.mark.parametrize('target', ['code', 'profile', 'backup'])
def test_rollback_refuses_later_changes_before_writing_anything(deployment, target):
    f = deployment
    pack.promote(*f.args, apply=True, desktop_stopped=True, allow_paid=True,
                 expected_sha256=config.digest(f.release / pack.RELEASE))
    file = {'code': f.build / 'server.py', 'profile': f.file, 'backup': f.backup / 'build/server.py'}[target]
    file.write_bytes(b'user-edited-after-deployment')
    profile_before = f.file.read_bytes()
    with pytest.raises(ValueError, match='desktop_codex_rollback_'):
        pack.rollback(f.backup, apply=True, desktop_stopped=True)
    assert file.read_bytes() == b'user-edited-after-deployment'
    assert f.file.read_bytes() == profile_before
    assert f.layout.read_bytes() == b'original-layout-data'


def test_promotion_refuses_build_or_backup_overlapping_layout_store(deployment):
    f = deployment
    for backup in (Path(f.profile['facilityRoot']) / 'backup', f.source / 'backup'):
        with pytest.raises(ValueError, match='desktop_codex_paths_overlap'):
            pack.promote(f.release, f.build, f.file, backup, allow_paid=True)


@pytest.mark.parametrize('path', ['../server.py', '/absolute.py', '.env', 'static/../../.env', 'a\\b', 'C:/file.py'])
def test_manifest_rejects_escape_and_dotenv_paths(path):
    with pytest.raises(ValueError):
        pack.relative_path(path)


def test_dependency_version_mismatch_and_extra_file_fail_closed(deployment):
    f = deployment
    root = f.release / pack.DEPS
    (root / 'unexpected.py').write_text('# changed after validation', encoding='utf-8')
    with pytest.raises(ValueError, match='desktop_codex_package_mismatch'):
        pack.verify_release(f.release)
    metadata = root / 'mcp-2.3.0.dist-info/METADATA'
    metadata.write_text('Name: mcp\nVersion: 2.4.0\n', encoding='utf-8')
    with pytest.raises(ValueError, match='desktop_codex_dependency_pin_mismatch'):
        config.dependency_versions(root)


def test_vault_read_is_profile_scoped_and_frees_zeroed_buffer(monkeypatch):
    secret = b'test-only-vault-credential-' + b'x' * 32
    blob = (ctypes.c_ubyte * len(secret))(*secret)
    item = credentials.Credential(Type=1, CredentialBlobSize=len(blob), CredentialBlob=blob)
    pointer = ctypes.pointer(item)
    calls = []
    def read(target, kind, flags, output):
        calls.append((target, kind, flags))
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(credentials.Credential)))[0] = pointer
        return True
    def free(_):
        assert bytes(blob) == bytes(len(secret))
        calls.append('freed')
    monkeypatch.setattr(credentials, '_vault', lambda: SimpleNamespace(CredReadW=read, CredFree=free))
    assert credentials.read_api_key('test') == secret.decode('ascii')
    assert calls == [('InspectorPro/Codex/test', 1, 0), 'freed']


def test_vault_write_uses_local_user_generic_credential_without_logging(monkeypatch, capsys):
    secret = 'test-only-vault-credential-' + 'x' * 32
    captured = []
    def write(value, flags):
        item = ctypes.cast(value, ctypes.POINTER(credentials.Credential)).contents
        assert item.TargetName == 'InspectorPro/Codex/test'
        assert (item.Type, item.Persist, flags) == (1, 2, 0)
        assert ctypes.string_at(item.CredentialBlob, item.CredentialBlobSize) == secret.encode('ascii')
        captured.append((item.CredentialBlob, item.CredentialBlobSize))
        return True
    monkeypatch.setattr(credentials, '_vault', lambda: SimpleNamespace(CredWriteW=write))
    credentials.store_api_key('test', secret)
    assert secret not in str(capsys.readouterr())
    assert len(captured) == 1


def test_missing_vault_record_is_fixed_failure(monkeypatch):
    monkeypatch.setattr(credentials, '_vault', lambda: SimpleNamespace(CredReadW=lambda *args: False))
    with pytest.raises(ValueError, match='^desktop_codex_credential_unavailable$'):
        credentials.read_api_key('test')
