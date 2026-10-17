import json
import uuid

import pytest

from desktop.runtime.application_profile import load_application_profile


@pytest.fixture
def profile(tmp_path):
    config = tmp_path / 'gateway.json'
    config.write_text('{}', encoding='utf-8')
    dependencies = tmp_path / 'dependencies'
    (dependencies / 'litellm').mkdir(parents=True)
    (dependencies / 'litellm/__init__.py').touch()
    value = dict(schemaVersion=1, mode='application', profileId='test', origin='http://127.0.0.1:8480',
                 dataRoot=str(tmp_path), facilityRoot=str(tmp_path), libraryRoot=str(tmp_path),
                 backendId=str(uuid.uuid4()), storeId=str(uuid.uuid4()), startupLayoutId='fl-test')
    gateway = dict(configPath=str(config), dependencyRoot=str(dependencies))
    def load(updated):
        file = tmp_path / 'profile.json'
        file.write_text(json.dumps(updated), encoding='utf-8')
        return load_application_profile(file)
    return value, gateway, load


def test_optional_gateway_preserves_store_identity(profile):
    value, gateway, load = profile
    original = load(value)
    enabled = load(dict(value, modelGateway=gateway))
    assert enabled.store_binding == original.store_binding
    assert enabled.value['modelGateway'] == gateway


@pytest.mark.parametrize('invalid', [None, [], {}, {'apiKey': 'not-allowed'},
                                     {'configPath': 'relative.json', 'dependencyRoot': 'relative'}])
def test_invalid_gateway_fails_closed(profile, invalid):
    value, _, load = profile
    with pytest.raises((ValueError, OSError)):
        load(dict(value, modelGateway=invalid))


def test_missing_gateway_dependencies_reject_profile(profile):
    value, gateway, load = profile
    from pathlib import Path
    Path(gateway['dependencyRoot'], 'litellm/__init__.py').unlink()
    with pytest.raises((ValueError, OSError)):
        load(dict(value, modelGateway=gateway))
