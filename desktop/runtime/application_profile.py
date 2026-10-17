"""Explicit bindings for a normal application, separate from acceptance stores."""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
import uuid

from desktop.runtime.profile import local_path

KEYS = {'schemaVersion', 'mode', 'profileId', 'origin', 'dataRoot', 'backendId', 'storeId',
        'facilityRoot', 'libraryRoot', 'startupLayoutId'}


@dataclass(frozen=True)
class ApplicationProfile:
    value: dict

    @property
    def data(self): return Path(self.value['dataRoot'])

    @property
    def origin(self): return self.value['origin']

    @property
    def layout_id(self): return self.value['startupLayoutId']

    @property
    def store_binding(self):
        return hashlib.sha256(json.dumps({k: self.value[k] for k in
            ('backendId', 'storeId', 'facilityRoot', 'libraryRoot')}, sort_keys=True).encode()).hexdigest()


def load_application_profile(file):
    file = local_path(file)
    if file.stat().st_size > 16384: raise ValueError('Application profile is too large')
    value = json.loads(file.read_text(encoding='utf-8'))
    if (not isinstance(value, dict) or not KEYS <= set(value) or set(value) - KEYS - {'modelGateway', 'codexRuntime'}
            or type(value['schemaVersion']) is not int
            or value['schemaVersion'] != 1 or value['mode'] != 'application'
            or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', value['profileId'])):
        raise ValueError('Invalid application profile')
    for key in ('backendId', 'storeId'):
        if str(uuid.UUID(value[key])) != value[key]: raise ValueError('Invalid identity')
    url = urlsplit(value['origin'])
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or url.port is None
            or not 1024 <= url.port <= 65535 or value['origin'] != f'http://127.0.0.1:{url.port}'):
        raise ValueError('Invalid application origin')
    if value['startupLayoutId'] is not None and not re.fullmatch(r'fl-[A-Za-z0-9._-]{1,128}', value['startupLayoutId']):
        raise ValueError('Invalid startup layout')
    for key in ('dataRoot', 'facilityRoot', 'libraryRoot'):
        target = local_path(Path(value[key]))
        if not target.is_dir(): raise ValueError('Application store is unavailable')
        value[key] = str(target)
    if 'modelGateway' in value:
        gateway = value['modelGateway']
        if not isinstance(gateway, dict) or set(gateway) != {'configPath', 'dependencyRoot'}:
            raise ValueError('Invalid desktop gateway profile')
        config = local_path(Path(gateway['configPath']))
        dependencies = local_path(Path(gateway['dependencyRoot']))
        module = local_path(dependencies / 'litellm' / '__init__.py')
        if not config.is_file() or config.stat().st_size > 65536 or not dependencies.is_dir() or not module.is_file():
            raise ValueError('Desktop gateway files are unavailable')
        value['modelGateway'] = {'configPath': str(config), 'dependencyRoot': str(dependencies)}
    if 'codexRuntime' in value:
        from desktop.runtime.codex_config import validate_config
        value['codexRuntime'] = validate_config(value['codexRuntime'], value)
    return ApplicationProfile(value)
