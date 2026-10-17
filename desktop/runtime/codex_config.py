"""Bounded desktop configuration. Credentials never appear in profile JSON."""
import hashlib
import importlib.metadata
import io
import os
from pathlib import Path
import re
import site
import sys
import threading

from desktop.runtime.codex_credentials import credential_target, read_api_key, validate_key
from desktop.runtime.profile import local_path, read_json

PINS = {'openai-codex-cli-bin': '0.162.1', 'mcp': '2.3.0', 'jsonschema': '4.26.0'}
MODEL = 'gpt-5.5'
PACKAGE = 'inspectorpro-codex-package.json'
KEYS = {'schemaVersion', 'model', 'editPreviews', 'allowPaidInference', 'dependencyRoot',
        'binary', 'pilotRoot', 'credentialTarget', 'packageSha256'}
ENV_DEFAULTS = {name: '' for name in ('BINARY', 'PILOT_ROOT', 'MODEL', 'API_KEY', 'MCP_TOKEN', 'AUTH_ROOT', 'AUTH_PROFILE_ID')}
ENV_DEFAULTS.update(READONLY_PILOT='0', EDIT_PREVIEWS='0', ALLOW_PAID_INFERENCE='0',
                    ALLOW_SUBSCRIPTION_INFERENCE='0', AUTH_MODE='api_key')


def digest(file):
    with Path(file).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def dependency_versions(root):
    versions = {}
    for item in importlib.metadata.distributions(path=[str(root)]):
        name = re.sub(r'[-_.]+', '-', item.metadata['Name']).lower()
        if name in versions:
            raise ValueError('desktop_codex_duplicate_dependency')
        versions[name] = item.version
    if any(versions.get(name) != version for name, version in PINS.items()):
        raise ValueError('desktop_codex_dependency_pin_mismatch')
    return dict(sorted(versions.items()))


def dependency_files(root, *, allow_cache=False):
    root = local_path(root)
    result = []
    for current, folders, names in os.walk(root, followlinks=False):
        directory = local_path(current)
        # Validate shared ancestors once per directory, then reject links on
        # each child. Rewalking every file's ancestors dominates Windows startup.
        for name in folders:
            child = directory / name
            if child.is_symlink() or getattr(child, 'is_junction', lambda: False)():
                raise ValueError('desktop_codex_dependency_link_refused')
        if not allow_cache and ('__pycache__' in folders or any(name.endswith(('.pyc', '.pyo')) for name in names)):
            raise ValueError('desktop_codex_dependency_cache_refused')
        folders[:] = sorted(name for name in folders if name != '__pycache__')
        for name in sorted(names):
            relative = (directory / name).relative_to(root)
            if relative.as_posix() == PACKAGE or (allow_cache and name.endswith(('.pyc', '.pyo'))):
                continue
            if (any(part.lower().startswith('.env') for part in relative.parts)
                    or name.lower() in {'auth.json', 'credentials.json', 'secrets.json'}
                    or name.lower().endswith(('.key', '.pem', '.db', '.sqlite', '.log'))):
                raise ValueError('desktop_codex_dependency_private_file_refused')
            file = directory / name
            if file.is_symlink() or getattr(file, 'is_junction', lambda: False)():
                raise ValueError('desktop_codex_dependency_link_refused')
            if not file.is_file():
                raise ValueError('desktop_codex_dependency_file_invalid')
            result.append({'path': relative.as_posix(), 'bytes': file.stat().st_size, 'sha256': digest(file)})
    return sorted(result, key=lambda item: item['path'])


def verify_dependency_package(root, expected_sha256):
    root = local_path(root)
    manifest = local_path(root / PACKAGE)
    if not isinstance(expected_sha256, str) or not re.fullmatch(r'[a-f0-9]{64}', expected_sha256):
        raise ValueError('desktop_codex_package_pin_required')
    if digest(manifest) != expected_sha256:
        raise ValueError('desktop_codex_package_hash_mismatch')
    package = read_json(manifest, 16 * 1024 * 1024)
    if (set(package) != {'schemaVersion', 'pins', 'versions', 'files', 'pythonTag', 'platform'}
            or type(package.get('schemaVersion')) is not int or package['schemaVersion'] != 1
            or package['pins'] != PINS or package['pythonTag'] != sys.implementation.cache_tag
            or package['platform'] != sys.platform or package['versions'] != dependency_versions(root)
            or package['files'] != dependency_files(root)):
        raise ValueError('desktop_codex_package_invalid')
    if 'codex_cli_bin/bin/codex.exe' not in {row['path'] for row in package['files']}:
        raise ValueError('desktop_codex_binary_missing')
    return package


def overlaps(a, b):
    return a == b or a in b.parents or b in a.parents


def validate_config(value, profile):
    try:
        from ai_inspector.codex_runtime.chatgpt_accounts import account_target
        subscription = isinstance(value, dict) and value.get('schemaVersion') == 2
        if (not isinstance(value, dict) or set(value) != (KEYS | {'authMode'} if subscription else KEYS)
                or type(value['schemaVersion']) is not int or value['schemaVersion'] not in {1, 2}
                or (subscription and value['authMode'] != 'chatgpt_plan')
                or value['model'] != ('gpt-6.1-sol' if subscription else MODEL) or type(value['editPreviews']) is not bool
                or value['allowPaidInference'] is not (False if subscription else True)
                or not isinstance(value['packageSha256'], str)
                or not re.fullmatch(r'[a-f0-9]{64}', value['packageSha256'])
                or value['credentialTarget'] != (account_target(profile['profileId']) if subscription else credential_target(profile['profileId']))):
            raise ValueError()
        dependencies, binary, pilot = (local_path(value[key]) for key in ('dependencyRoot', 'binary', 'pilotRoot'))
        data = local_path(profile['dataRoot'])
        if (not dependencies.is_dir() or not binary.is_file()
                or binary != dependencies / 'codex_cli_bin/bin/codex.exe'
                or pilot != data / 'codex-pilot'
                or any(overlaps(dependencies, local_path(profile[key]))
                       for key in ('dataRoot', 'facilityRoot', 'libraryRoot'))
                or any(root == pilot or root in pilot.parents or pilot in root.parents
                       for root in (local_path(profile['facilityRoot']), local_path(profile['libraryRoot']), dependencies))):
            raise ValueError()
        return dict(value, dependencyRoot=str(dependencies), binary=str(binary), pilotRoot=str(pilot))
    except Exception:
        raise ValueError('desktop_codex_config_invalid') from None


def validate_package(config, app_root):
    root = local_path(app_root)
    dependencies = local_path(config['dependencyRoot'])
    if overlaps(root, dependencies):
        # Embedded dependencies remain supported only for existing diagnostic
        # snapshots. Normal application mode uses a separate dependency bundle.
        if dependencies != root / '.runtime/codex-pilot-deps' or not (root / 'desktop-checkpoint.json').is_file():
            raise ValueError('desktop_codex_dependency_source_overlap')
        checkpoint = read_json(root / 'desktop-checkpoint.json')
        if overlaps(local_path(checkpoint['source']), root):
            raise ValueError('desktop_codex_dependency_source_overlap')
    if local_path(config['binary']) != dependencies / 'codex_cli_bin/bin/codex.exe':
        raise ValueError('desktop_codex_binary_path_invalid')
    return verify_dependency_package(dependencies, config['packageSha256'])


class RedactingStream(io.TextIOBase):
    """Keep split-write credential prefixes out of both startup output streams."""
    def __init__(self, stream, secret):
        self.stream, self.secret, self.pending = stream, secret, ''
        self._lock = threading.RLock()

    @property
    def encoding(self): return self.stream.encoding

    def writable(self): return True

    def write(self, value):
        with self._lock:
            text = (self.pending + value).replace(self.secret, '[redacted]')
            count = next((n for n in range(min(len(text), len(self.secret) - 1), 0, -1)
                          if text.endswith(self.secret[:n])), 0)
            self.pending = text[-count:] if count else ''
            self.stream.write(text[:-count] if count else text)
        return len(value)

    def flush(self):
        with self._lock:
            self.stream.flush()

    def isatty(self): return False


def configure_codex(profile, app_root, *, environment=None, credential_reader=read_api_key,
                    add_site=site.addsitedir, protect_output=True):
    env = os.environ if environment is None else environment
    # Explicit empty values also prevent server.py's non-overriding dotenv loader
    # from reactivating a removed profile configuration or supplying a different key.
    for name in list(env):
        if name.upper().startswith(('INSPECTORPRO_CODEX_', 'INSPECTORPRO_CHATGPT_', 'CODEX_')):
            del env[name]
    env.update({'INSPECTORPRO_CODEX_' + name: value for name, value in ENV_DEFAULTS.items()})
    if 'codexRuntime' not in profile.value:
        return
    config = validate_config(profile.value['codexRuntime'], profile.value)
    validate_package(config, app_root)
    subscription = config.get('authMode') == 'chatgpt_plan'
    key = ''
    if not subscription:
        try:
            key = validate_key(credential_reader(profile.value['profileId']))
        except Exception:
            raise ValueError('desktop_codex_credential_unavailable') from None
    if protect_output and key:
        sys.stdout = RedactingStream(sys.stdout, key)
        sys.stderr = RedactingStream(sys.stderr, key)
    # The verified dependency inventory is immutable; never create unchecked pyc.
    sys.dont_write_bytecode = True
    # Append after application dependencies, never prepend to PYTHONPATH. This
    # also processes the tested pywin32 .pth without replacing FastAPI/Starlette.
    add_site(config['dependencyRoot'])
    env.update({'INSPECTORPRO_CODEX_' + name: value for name, value in {
        'READONLY_PILOT': '1', 'EDIT_PREVIEWS': '1' if config['editPreviews'] else '0',
        'ALLOW_PAID_INFERENCE': '0' if subscription else '1',
        'ALLOW_SUBSCRIPTION_INFERENCE': '1' if subscription else '0',
        'AUTH_MODE': 'chatgpt_plan' if subscription else 'api_key',
        'AUTH_ROOT': str(Path(profile.value['dataRoot']) / 'chatgpt-auth') if subscription else '',
        'AUTH_PROFILE_ID': profile.value['profileId'] if subscription else '',
        'BINARY': config['binary'], 'PILOT_ROOT': config['pilotRoot'],
        'MODEL': config['model'], 'API_KEY': key}.items()})
