"""Stable, explicitly selected local developer stores for the desktop runtime."""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import uuid
from urllib.parse import urlsplit

SCHEMA_KEYS = {'schemaVersion', 'mode', 'profileId', 'origin', 'dataRoot', 'backendId', 'storeId', 'acceptanceLayoutId'}
MARKER = 'desktop-managed-store.json'


def local_path(path):
    # The actual facility repositories deliberately use Windows extended local
    # paths for long artifact names. Normalize that spelling, never UNC shares.
    raw = os.fspath(path)
    if raw.startswith('\\\\?\\') and not raw.upper().startswith('\\\\?\\UNC\\'):
        path = raw[4:]
    path = Path(path)
    if not path.is_absolute() or str(path).startswith('\\\\'):
        raise ValueError('Desktop paths must be absolute local filesystem paths')
    for item in (path, *path.parents):
        if item.exists() and (item.is_symlink() or getattr(item, 'is_junction', lambda: False)()):
            raise ValueError('Desktop paths may not traverse links or junctions')
    return path.resolve()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()


def read_json(path, maximum=65536):
    path = local_path(path)
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError('Desktop configuration is missing or oversized')
    return json.loads(path.read_text(encoding='utf-8-sig'))


def write_exclusive(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('xb') as stream:
        stream.write(canonical(value)); stream.flush(); os.fsync(stream.fileno())


@dataclass(frozen=True)
class RuntimeProfile:
    value: dict
    marker: dict
    data: Path

    @property
    def origin(self): return self.value['origin']

    @property
    def layout_id(self): return self.value['acceptanceLayoutId']

    @property
    def owner(self): return dict(self.marker['owner'])

    @property
    def capabilities(self):
        return {'generalEditing': False, 'researchBrowsing': False, 'facilityAcceptance': self.layout_id is not None}

    def identity(self, instance_id):
        return {'schemaVersion': 1, 'product': 'InspectorPro', 'mode': 'desktop-managed',
                **{key: self.value[key] for key in ('backendId', 'storeId', 'profileId')},
                'instanceId': instance_id, 'storeBinding': self.marker['storeBinding'],
                'capabilities': self.capabilities}


def prepare_profile(value, application_root):
    if not isinstance(value, dict) or set(value) != SCHEMA_KEYS or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1 or value['mode'] != 'managed':
        raise ValueError('Unsupported desktop managed profile schema')
    if not isinstance(value['profileId'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', value['profileId']):
        raise ValueError('Desktop profile ID is invalid')
    for key in ('backendId', 'storeId'):
        if not isinstance(value[key], str) or str(uuid.UUID(value[key])) != value[key]:
            raise ValueError('Desktop logical identity must be a canonical UUID')
    url = urlsplit(value['origin'])
    if (url.scheme != 'http' or url.hostname != '127.0.0.1' or url.username or url.password
            or url.path or url.query or url.fragment or not url.port or not 1024 <= url.port <= 65535
            or value['origin'] != 'http://127.0.0.1:' + str(url.port)):
        raise ValueError('Desktop origin must be an explicit IPv4 loopback origin and port')
    layout_id = value['acceptanceLayoutId']
    if layout_id is not None and (not isinstance(layout_id, str) or not re.fullmatch(r'fl-[A-Za-z0-9._-]{1,128}', layout_id)):
        raise ValueError('Desktop acceptance document ID is invalid')
    data, application_root = local_path(value['dataRoot']), local_path(application_root)
    if data == application_root or data in application_root.parents:
        raise ValueError('Desktop data cannot contain the application checkout')
    checkpoint = application_root / 'desktop-checkpoint.json'
    if checkpoint.exists():
        source = local_path(read_json(checkpoint)['source'])
        if data == source or source in data.parents or data in source.parents:
            raise ValueError('Desktop developer data may not overlap the live source workspace')
    elif application_root in data.parents:
        raise ValueError('Desktop developer data must be outside its application checkout')
    if layout_id is not None:
        manifest = read_json(data / 'facility-recovery-fixture.json', 4 * 1024 * 1024)
        if local_path(manifest.get('fixtureRoot', '')) != data or manifest.get('layout', {}).get('layoutId') != layout_id:
            raise ValueError('Acceptance requires the explicitly marked isolated document store')
        relative = Path(manifest['layout']['relativePath'])
        layout_path = local_path(data / relative)
        if data not in layout_path.parents or relative.is_absolute():
            raise ValueError('Isolated document path escapes its data root')
        if hashlib.sha256(layout_path.read_bytes()).hexdigest() != manifest['layout']['revision']:
            raise ValueError('Isolated document bytes differ from their provenance marker')
        source = local_path(manifest['source']['root'])
        if data == source or source in data.parents or data in source.parents:
            raise ValueError('Acceptance document store overlaps its live source')
    marker_path = data / MARKER
    roots = {name: str(local_path(data / folder)) for name, folder in
             (('dataRoot', '.'), ('libraryRoot', 'library'), ('facilityRoot', 'facility'), ('assetRoot', 'asset-project'))}
    binding = {'profileId': value['profileId'], 'backendId': value['backendId'], 'storeId': value['storeId'],
               'origin': value['origin'], 'acceptanceLayoutId': layout_id, 'roots': roots}
    store_binding = hashlib.sha256(canonical(binding)).hexdigest()
    expected = {'schemaVersion': 1, 'mode': 'desktop-managed-isolated', **binding, 'storeBinding': store_binding}
    if marker_path.exists():
        marker = read_json(marker_path)
        if any(marker.get(key) != expected[key] for key in expected) or set(marker) != set(expected) | {'owner'}:
            raise ValueError('Desktop profile does not own this authoritative store configuration')
        owner = marker.get('owner')
        if not isinstance(owner, dict) or set(owner) != {'sessionId', 'ownerId'} or any(not isinstance(item, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', item) for item in owner.values()):
            raise ValueError('Desktop profile owner is invalid')
    else:
        if layout_id is None and data.exists() and any(data.iterdir()):
            raise ValueError('Unmarked developer data root must be empty')
        marker = {**expected, 'owner': {'sessionId': 'desktop-session-' + uuid.uuid4().hex, 'ownerId': 'desktop-owner-' + uuid.uuid4().hex}}
        write_exclusive(marker_path, marker)
    for folder in ('library', 'facility', 'temp', 'localappdata', 'appdata', 'logs'):
        local_path(data / folder).mkdir(parents=True, exist_ok=True)
    return RuntimeProfile(dict(value), marker, data)


def load_profile(path, application_root):
    return prepare_profile(read_json(local_path(path)), application_root)
