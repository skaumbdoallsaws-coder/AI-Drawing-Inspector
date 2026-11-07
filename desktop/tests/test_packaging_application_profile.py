"""Offline native-profile contract tests; all paths and credentials are synthetic."""
import ast
import asyncio
import json
import os
from pathlib import Path
import shutil
import subprocess
from types import SimpleNamespace
import uuid

import pytest

from desktop.runtime.application_profile import ApplicationProfile, load_application_profile
from desktop.runtime.packaging_config import ENV_DEFAULTS, PACKAGES, REASONS, configure_packaging, validate_config

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    from ai_inspector.packaging_shipping import sources
    monkeypatch.setattr(sources, '_RUNTIME', None)
    stores = {key: str(tmp_path / name) for key, name in
              [('dataRoot', 'data'), ('facilityRoot', 'facility'), ('libraryRoot', 'library')]}
    for directory in stores.values():
        Path(directory).mkdir()
    dependencies = tmp_path / 'dependencies'
    for name in PACKAGES:
        (dependencies / name).mkdir(parents=True)
        (dependencies / name / '__init__.py').touch()
    python = tmp_path / 'step-venv' / 'python.exe'
    python.parent.mkdir()
    python.touch()
    profile = dict(schemaVersion=1, mode='application', profileId='packaging-test',
                   origin='http://127.0.0.1:8480', backendId=str(uuid.uuid4()),
                   storeId=str(uuid.uuid4()), startupLayoutId=None, **stores)
    config = dict(schemaVersion=1, dependencyRoot=str(dependencies), geometryPython=str(python))
    file = tmp_path / 'profile.json'

    def load(value):
        file.write_text(json.dumps(value), encoding='utf-8')
        return load_application_profile(file)

    return SimpleNamespace(profile=profile, config=config, file=file, load=load, root=tmp_path)


def invalid_configs(f):
    values = [None, False, [], {}, {'schemaVersion': 1}, {'dependencyRoot': f.config['dependencyRoot']}]
    for key, options in {
        'schemaVersion': [True, False, 0, 2, 1.5, '1', None],
        'enabled': [True, False], 'apiKey': ['synthetic-secret'], 'root': [str(f.root)],
        'geometryPython': [None, False, 3, [], {}, '', 'relative.exe', '\\\\host\\share\\python.exe',
                           '//host/share/python', '/\\host/share/python', '\\/host/share/python',
                           '\\root-relative.exe', 'C:drive-relative.exe', '\\\\?\\C:\\python.exe', str(f.root / 'missing.exe'),
                           f.profile['dataRoot'], str(f.root / 'step-venv' / '..' / 'step-venv' / 'python.exe'),
                           str(f.root / 'step-venv' / 'python.exe') + '\x00'],
        'dependencyRoot': [None, False, 3, [], {}, '', 'relative', '\\\\host\\share\\deps',
                           '//host/share/deps', '/\\host/share/deps', '\\/host/share/deps',
                           '\\root-relative', 'C:drive-relative', str(f.root / 'missing'), f.config['geometryPython'],
                           str(f.root / 'dependencies' / '..' / 'dependencies')],
    }.items():
        values.extend(dict(f.config, **{key: value}) for value in options)
    return values


def test_optional_profile_keeps_identity_and_creates_no_state(fixture):
    f = fixture
    original = f.load(f.profile)
    for config in [f.config, {k: v for k, v in f.config.items() if k != 'geometryPython'}]:
        enabled = f.load(dict(f.profile, packagingRuntime=config))
        assert enabled.store_binding == original.store_binding
        assert enabled.value['packagingRuntime'] == config
    assert 'packagingRuntime' not in original.value
    assert not (Path(f.profile['dataRoot']) / 'packaging').exists()


def test_malformed_configs_are_refused_without_echoing_values_and_never_stop_startup(fixture):
    f = fixture
    binding = f.load(f.profile).store_binding
    without_step = {k: v for k, v in f.config.items() if k != 'geometryPython'}
    for config in invalid_configs(f):
        with pytest.raises(ValueError, match='^desktop_packaging_config_invalid$') as refused:
            validate_config(config, f.profile)
        assert refused.value.reason in REASONS
        loaded = f.load(dict(f.profile, packagingRuntime=config))
        assert loaded.packaging_unavailable == refused.value.reason
        assert loaded.store_binding == binding
        if refused.value.reason == 'step-python':
            assert loaded.value['packagingRuntime'] == without_step
        else:
            assert 'packagingRuntime' not in loaded.value


@pytest.mark.parametrize('damage, reason', [('package', 'package:trimesh'), ('folder', 'dependency-folder'),
                                            ('storage', 'storage'), ('step', 'step-python')])
def test_unusable_runtime_starts_without_packaging_and_names_the_reason(fixture, damage, reason):
    f = fixture
    if damage == 'package':
        shutil.rmtree(Path(f.config['dependencyRoot']) / 'trimesh')
    elif damage == 'folder':
        shutil.rmtree(f.config['dependencyRoot'])
    elif damage == 'storage':
        (Path(f.profile['dataRoot']) / 'packaging').write_bytes(b'')
    else:
        Path(f.config['geometryPython']).unlink()
    profile = f.load(dict(f.profile, packagingRuntime=f.config))
    assert profile.packaging_unavailable == reason
    env, paths = {}, ['base-app-deps']
    configure_packaging(profile, environment=env, search_path=paths)
    if damage == 'step':
        # Only STEP import is off: manual packing, reports and the dependency folder stay in use.
        assert profile.value['packagingRuntime'] == {k: v for k, v in f.config.items() if k != 'geometryPython'}
        assert env['INSPECTORPRO_PACKAGING_ENABLED'] == '1' and env['INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON'] == ''
        assert paths == ['base-app-deps', f.config['dependencyRoot']]
    else:
        assert 'packagingRuntime' not in profile.value
        assert env == ENV_DEFAULTS and paths == ['base-app-deps']
    with pytest.raises(ValueError, match='^desktop_packaging_config_invalid$'):
        validate_config(f.config, f.profile)  # Enabling Packaging stays strict.


@pytest.mark.parametrize('name', PACKAGES)
def test_each_required_package_must_be_a_regular_file(fixture, name):
    module = Path(fixture.config['dependencyRoot']) / name / '__init__.py'
    module.unlink()
    with pytest.raises(ValueError, match='desktop_packaging_config_invalid') as refused:
        validate_config(fixture.config, fixture.profile)
    assert refused.value.reason == 'package:' + name
    module.mkdir()
    with pytest.raises(ValueError, match='desktop_packaging_config_invalid') as refused:
        validate_config(fixture.config, fixture.profile)
    assert refused.value.reason == 'package:' + name
    loaded = fixture.load(dict(fixture.profile, packagingRuntime=fixture.config))
    assert 'packagingRuntime' not in loaded.value and loaded.packaging_unavailable == 'package:' + name


@pytest.mark.parametrize('target', ['packaging', 'packaging/step-jobs'])
def test_state_paths_cannot_be_files(fixture, target):
    file = Path(fixture.profile['dataRoot']) / target
    file.parent.mkdir(parents=True, exist_ok=True)
    file.touch()
    with pytest.raises(ValueError, match='desktop_packaging_config_invalid') as refused:
        validate_config(fixture.config, fixture.profile)
    assert refused.value.reason == 'storage'


def test_dependencies_and_geometry_cannot_overlap_stores_or_each_other(fixture):
    f = fixture
    for key in ('dataRoot', 'facilityRoot', 'libraryRoot'):
        with pytest.raises(ValueError) as refused:
            validate_config(f.config, dict(f.profile, **{key: f.config['dependencyRoot']}))
        assert refused.value.reason == 'dependency-folder'
        with pytest.raises(ValueError) as refused:
            validate_config(f.config, dict(f.profile, **{key: str(Path(f.config['geometryPython']).parent)}))
        assert refused.value.reason == 'step-python'
    with pytest.raises(ValueError) as refused:
        validate_config(dict(f.config, geometryPython=str(Path(f.config['dependencyRoot']) / 'py3dbp/__init__.py')), f.profile)
    assert refused.value.reason == 'step-python'


def test_disabled_scrubs_inheritance_and_blocks_dotenv_without_touching_auth(fixture):
    auth = {'INSPECTORPRO_CODEX_AUTH_MODE': 'chatgpt_plan', 'INSPECTORPRO_CODEX_API_KEY': '',
            'INSPECTORPRO_CODEX_AUTH_ROOT': 'synthetic-auth', 'INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE': '0',
            'INSPECTORPRO_CHATGPT_TEST': 'synthetic-account', 'OPENAI_API_KEY': 'synthetic-legacy'}
    env = dict(auth, **{key.lower(): 'inherited' for key in ENV_DEFAULTS}, INSPECTORPRO_PACKAGING_UNKNOWN='1')
    paths = ['base-app-deps']
    configure_packaging(ApplicationProfile(fixture.profile), environment=env, search_path=paths)
    assert all(env[key] == value for key, value in auth.items())
    assert all(env[key] == value for key, value in ENV_DEFAULTS.items())
    assert 'INSPECTORPRO_PACKAGING_UNKNOWN' not in env
    assert not any(key.lower() == key for key in env)
    for key in ENV_DEFAULTS:
        env.setdefault(key, 'dotenv-attempt')
    assert env['INSPECTORPRO_PACKAGING_ENABLED'] == env['INSPECTORPRO_CODEX_PACKAGING'] == '0'
    assert paths == ['base-app-deps']


@pytest.mark.parametrize('geometry', [False, True])
@pytest.mark.parametrize('codex', [False, True])
def test_enabled_uses_selected_data_root_and_separate_step_runtime(fixture, geometry, codex):
    f = fixture
    config = dict(f.config)
    if not geometry:
        del config['geometryPython']
    profile = dict(f.profile, packagingRuntime=config)
    if codex:
        profile['codexRuntime'] = {'test': 'already validated by profile loader'}
    env = {key: 'stale' for key in ENV_DEFAULTS}
    paths = ['base-app-deps']
    for _ in range(2):
        configure_packaging(ApplicationProfile(profile), environment=env, search_path=paths)
    root = Path(f.profile['dataRoot']) / 'packaging'
    assert env['INSPECTORPRO_PACKAGING_ENABLED'] == '1'
    assert env['INSPECTORPRO_CODEX_PACKAGING'] == ('1' if codex else '0')
    assert env['INSPECTORPRO_PACKAGING_ROOT'] == str(root)
    assert env['INSPECTORPRO_PACKAGING_GEOMETRY_TMP'] == str(root / 'step-jobs')
    assert env['INSPECTORPRO_PACKAGING_GEOMETRY_PYTHON'] == (config['geometryPython'] if geometry else '')
    assert env['INSPECTORPRO_PACKAGING_EASYPOST_KEY'] == ''
    assert paths == ['base-app-deps', config['dependencyRoot']]
    assert not root.exists()


def test_invalid_runtime_stays_off_before_dependency_injection(fixture):
    # Reached only when a runtime broke after the profile loaded: Packaging stays off and nothing is injected.
    from ai_inspector.packaging_shipping import sources
    env = {key: '1' for key in ENV_DEFAULTS}
    paths = []
    configure_packaging(ApplicationProfile(dict(fixture.profile, packagingRuntime={})), environment=env, search_path=paths)
    assert env == ENV_DEFAULTS
    assert paths == []
    assert sources._RUNTIME is None


def test_chatgpt_configuration_is_unchanged_and_no_credential_reader_runs(fixture, monkeypatch):
    from desktop.runtime import codex_config
    f = fixture
    dependencies = f.root / 'codex-deps'
    binary = dependencies / 'codex_cli_bin/bin/codex.exe'
    binary.parent.mkdir(parents=True)
    binary.touch()
    config = dict(schemaVersion=2, model='gpt-6.1-sol', editPreviews=True, allowPaidInference=False,
                  authMode='chatgpt_plan', dependencyRoot=str(dependencies), binary=str(binary),
                  pilotRoot=str(Path(f.profile['dataRoot']) / 'codex-pilot'),
                  credentialTarget='InspectorPro/ChatGPT/packaging-test', packageSha256='a' * 64)
    profile = f.load(dict(f.profile, codexRuntime=config, packagingRuntime=f.config))
    monkeypatch.setattr(codex_config, 'validate_package', lambda *_: None)

    def refuse_credentials(*_):
        pytest.fail('Packaging must not read credentials')

    env = {}
    codex_config.configure_codex(profile, f.root, environment=env, credential_reader=refuse_credentials,
                                add_site=lambda _: None, protect_output=False)
    before = dict(env)
    configure_packaging(profile, environment=env, search_path=[])
    assert all(env[key] == value for key, value in before.items())
    assert env['INSPECTORPRO_CODEX_PACKAGING'] == '1'
    assert env['INSPECTORPRO_CODEX_ALLOW_PAID_INFERENCE'] == '0'
    assert env['INSPECTORPRO_CODEX_AUTH_ROOT'] == str(Path(f.profile['dataRoot']) / 'chatgpt-auth')


def test_backend_configures_packaging_after_codex_before_serve():
    source = (ROOT / 'desktop/runtime/application_backend.py').read_text(encoding='utf-8')
    calls = {node.func.id: node.lineno for node in ast.walk(ast.parse(source))
             if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)}
    assert calls['configure_codex'] < calls['configure_packaging'] < calls['serve']


def test_packaging_routes_keep_native_private_token_boundary(fixture):
    from desktop.runtime.application_boundary import ApplicationBoundary
    calls = []

    async def app(scope, receive, send):
        calls.append(scope)
        await send({'type': 'http.response.start', 'status': 204, 'headers': []})

    boundary = ApplicationBoundary(app, ApplicationProfile(fixture.profile), 'a' * 64, 'instance', None)

    async def request(token):
        result = []

        async def send(value):
            result.append(value)

        scope = {'type': 'http', 'path': '/api/packaging/designs', 'method': 'POST',
                 'headers': [(b'host', b'127.0.0.1:8480')] +
                 ([(b'x-inspectorpro-desktop-token', b'a' * 64)] if token else [])}
        await boundary(scope, None, send)
        return result[0]['status']

    assert asyncio.run(request(False)) == 401
    assert calls == []
    assert asyncio.run(request(True)) == 204
    assert not any(name == b'x-inspectorpro-desktop-token' for name, _ in calls[0]['headers'])


def test_node_and_python_loaders_agree_on_same_profiles(fixture):
    node = shutil.which('node')
    assert node, 'Node is required for native profile parity'
    f = fixture
    profiles = [f.profile, dict(f.profile, packagingRuntime=f.config),
                dict(f.profile, packagingRuntime={k: v for k, v in f.config.items() if k != 'geometryPython'}),
                dict(f.profile, packagingRuntime=dict(f.config, schemaVersion=1.0))]
    profiles += [dict(f.profile, packagingRuntime=value) for value in invalid_configs(f)]
    # A directory junction needs no Windows symlink privilege; test both loaders.
    link = f.root / 'linked-deps'
    subprocess.run([node, '-e', "require('node:fs').symlinkSync(process.argv[1],process.argv[2],'junction')",
                    f.config['dependencyRoot'], str(link)], check=True, capture_output=True, timeout=15,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    profiles.append(dict(f.profile, packagingRuntime=dict(f.config, dependencyRoot=str(link))))
    files, expected = [], []
    for index, value in enumerate(profiles):
        file = f.root / f'parity-{index}.json'
        file.write_text(json.dumps(value), encoding='utf-8')
        files.append(str(file))
        try:
            loaded = load_application_profile(file)
            expected.append({'valid': True, 'config': loaded.value.get('packagingRuntime'),
                             'unavailable': loaded.packaging_unavailable})
        except ValueError:
            expected.append({'valid': False})
    script = """const {loadApplicationProfile} = require('./desktop/src/application-profile.cjs');
let input = ''; process.stdin.on('data', b => input += b);
process.stdin.on('end', async () => {
  const results = [];
  for (const file of JSON.parse(input)) {
    try { const p = await loadApplicationProfile(file); results.push({valid: true, config: p.packagingRuntime ?? null, unavailable: p.packagingUnavailable ?? null}); }
    catch (_) { results.push({valid: false}); }
  }
  process.stdout.write(JSON.stringify(results));
});"""
    result = subprocess.run([node, '-e', script], input=json.dumps(files), text=True, capture_output=True,
                            cwd=ROOT, timeout=30, check=True,
                            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    assert json.loads(result.stdout) == expected
    # Every refused runtime still starts the application, with Packaging (or only STEP) off and a reason.
    assert all(item['valid'] and item['unavailable'] is None for item in expected[:4])
    assert all(item['valid'] and item['unavailable'] in REASONS for item in expected[4:])
