import json
from uuid import uuid4

import pytest

from tools.enable_desktop_packaging import enable


def fixture(tmp_path):
    roots = {}
    for key in ('dataRoot', 'facilityRoot', 'libraryRoot'):
        target = tmp_path / key
        target.mkdir()
        roots[key] = str(target)
    dependencies = tmp_path / 'dependencies'
    for name in ('py3dbp', 'trimesh', 'reportlab'):
        folder = dependencies / name
        folder.mkdir(parents=True)
        (folder / '__init__.py').write_text('')
    geometry = tmp_path / 'geometry-python.exe'
    geometry.write_bytes(b'fixture-not-executed')
    value = dict(schemaVersion=1, mode='application', profileId='test-packaging-promotion',
                 origin='http://127.0.0.1:58801', backendId=str(uuid4()), storeId=str(uuid4()),
                 startupLayoutId='fl-existing-layout', **roots)
    file = tmp_path / 'profile.json'
    file.write_text(json.dumps(value))
    return file, dependencies, geometry, value


def test_promotion_changes_only_packaging_keeps_exact_backup_and_is_idempotent(tmp_path):
    file, dependencies, geometry, original = fixture(tmp_path)
    before = file.read_bytes()
    enable(file, dependencies, geometry)
    promoted = json.loads(file.read_text())
    assert promoted.pop('packagingRuntime') == dict(schemaVersion=1,
        dependencyRoot=str(dependencies), geometryPython=str(geometry))
    assert promoted == original
    backups = list(tmp_path.glob('profile.json.before-packaging-*'))
    assert len(backups) == 1
    assert backups[0].read_bytes() == before
    after = file.read_bytes()
    enable(file, dependencies, geometry)
    assert file.read_bytes() == after
    assert list(tmp_path.glob('profile.json.before-packaging-*')) == backups


def test_invalid_dependencies_leave_profile_and_backup_state_unchanged(tmp_path):
    file, dependencies, geometry, _ = fixture(tmp_path)
    before = file.read_bytes()
    (dependencies / 'trimesh' / '__init__.py').unlink()
    with pytest.raises(ValueError):
        enable(file, dependencies, geometry)
    assert file.read_bytes() == before
    assert not list(tmp_path.glob('profile.json.before-packaging-*'))
