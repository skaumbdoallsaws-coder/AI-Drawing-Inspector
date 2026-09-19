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
    if (not isinstance(value, dict) or set(value) != KEYS or type(value['schemaVersion']) is not int
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
    return ApplicationProfile(value)
