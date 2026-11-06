"""Host-bound dependency propagation; no personal profiles, credentials or network."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ai_inspector.facility_layout.authorization import FacilityPrincipal
from ai_inspector.packaging_shipping import sources, api
from ai_inspector.packaging_shipping.service import PackagingError, PackagingService
from ai_inspector.packaging_shipping.sources import GlbRuntime


@pytest.fixture
def bound(tmp_path, monkeypatch):
    dependencies = tmp_path / 'release-dependencies'
    dependencies.mkdir()
    monkeypatch.setattr(sources, '_RUNTIME', None)
    sources.configure_glb_runtime(dependencies)
    return dependencies


def test_binding_is_explicit_and_can_be_cleared(bound, monkeypatch):
    assert sources.glb_runtime().dependency_root == bound
    monkeypatch.setenv('INSPECTORPRO_PACKAGING_DEPENDENCY_ROOT', 'not-selected')
    monkeypatch.setenv('PYTHONPATH', 'not-selected')
    assert sources.glb_runtime().dependency_root == bound
    sources.configure_glb_runtime()
    assert sources.glb_runtime().dependency_root != bound


@pytest.mark.parametrize('path', ['', 'relative', '../outside', '\\\\host\\share', '//host/share'])
def test_nonlocal_or_relative_dependency_root_is_rejected(path):
    with pytest.raises(ValueError, match='glb_dependency_root_invalid'):
        GlbRuntime(path)


def test_invalid_runtime_cannot_come_from_upload_data(tmp_path):
    with pytest.raises(TypeError):
        asyncio.run(sources.import_glb_isolated(b'fixture', 'fixture', 1, tmp_path,
                                              runtime={'dependencyRoot': str(tmp_path)}))


def test_real_worker_ignores_pth_customization_cwd_and_inherited_pythonpath(bound, tmp_path, monkeypatch):
    canary = tmp_path / 'must-not-run'
    poison = "from pathlib import Path; Path(" + repr(str(canary)) + ").touch(); raise RuntimeError('unexpected startup hook')\n"
    (bound / 'poison.pth').write_text('import pathlib; pathlib.Path(' + repr(str(canary)) + ').touch()\n', encoding='ascii')
    (bound / 'sitecustomize.py').write_text(poison, encoding='ascii')
    (bound / 'usercustomize.py').write_text(poison, encoding='ascii')
    inherited = tmp_path / 'inherited'
    inherited.mkdir()
    (inherited / 'numpy.py').write_text(poison, encoding='ascii')
    monkeypatch.setenv('PYTHONPATH', str(inherited))
    monkeypatch.setenv('PYTHONHOME', str(inherited))
    monkeypatch.setenv('OPENAI_API_KEY', 'synthetic-secret')
    monkeypatch.setenv('INSPECTORPRO_PACKAGING_EASYPOST_KEY', 'synthetic-carrier')
    # A synthetic parser module audits the real worker startup without depending
    # on a host NumPy installation. Real parsing is covered by release acceptance.
    (bound / 'numpy.py').write_text("""import json, os, sys
from pathlib import Path
value = {'no_site': sys.flags.no_site, 'isolated': sys.flags.isolated,
         'no_user_site': sys.flags.no_user_site, 'dont_write_bytecode': sys.dont_write_bytecode,
         'paths': sys.path, 'cwd': str(Path.cwd()),
         'leaked': [k for k in os.environ if k.startswith(('PYTHON', 'INSPECTORPRO_', 'OPENAI_'))]}
Path('metadata.json').write_text(json.dumps(value))
Path('normalized.glb').write_bytes(b'glTF-test-fixture')
raise SystemExit(0)
""", encoding='ascii')
    value, _ = asyncio.run(sources.import_glb_isolated(b'fixture', 'fixture', 1, tmp_path / 'state'))
    assert value['no_site'] == value['isolated'] == value['no_user_site'] == 1
    assert value['dont_write_bytecode'] is True
    assert value['leaked'] == []
    assert str(bound) in value['paths']
    assert str(inherited) not in value['paths']
    assert value['cwd'] not in value['paths'] and '' not in value['paths']
    assert not canary.exists()
    assert list((tmp_path / 'state/import-jobs').iterdir()) == []


def test_router_captures_startup_binding_and_ignores_request_paths(bound, tmp_path, monkeypatch):
    captured = []

    async def parser(payload, name, units, root, *, runtime):
        captured.append(runtime)
        raise PackagingError('fixture_parser', 'fixture parser reached', 422)

    monkeypatch.setattr(api, 'import_glb_isolated', parser)
    principal = FacilityPrincipal('fixture', 'local', ('site-local',), ('editor',))
    app = FastAPI()
    app.include_router(api.create_router(PackagingService(tmp_path / 'state'),
                       principal_resolver=lambda _: principal, static_root=tmp_path,
                       rating=object()))
    other = tmp_path / 'other'
    other.mkdir()
    sources.configure_glb_runtime(other)
    with TestClient(app, headers={'x-inspectorpro-request': 'packaging'}) as client:
        response = client.post('/api/packaging/sources', params={
            'dependencyRoot': str(other), 'dependency_root': str(other), 'geometryPython': str(other)},
            headers={'x-pythonpath': str(other)}, content=b'fixture')
    assert response.status_code == 422
    assert [value.dependency_root for value in captured] == [bound]


def test_native_startup_reuses_validated_root_and_disabled_clears_binding(bound, tmp_path):
    from desktop.runtime.packaging_config import configure_packaging
    from desktop.runtime.application_profile import ApplicationProfile
    for name in ('py3dbp', 'trimesh', 'reportlab'):
        (bound / name).mkdir()
        (bound / name / '__init__.py').touch()
    value = {}
    for key in ('dataRoot', 'facilityRoot', 'libraryRoot'):
        value[key] = str(tmp_path / key)
        Path(value[key]).mkdir()
    value['packagingRuntime'] = {'schemaVersion': 1, 'dependencyRoot': str(bound)}
    configure_packaging(ApplicationProfile(value), environment={}, search_path=[])
    assert sources.glb_runtime().dependency_root == bound
    del value['packagingRuntime']
    configure_packaging(ApplicationProfile(value), environment={}, search_path=[])
    assert sources._RUNTIME is None


def test_step_worker_disables_site_processing(tmp_path, monkeypatch):
    from ai_inspector.packaging_shipping import step_import
    worker = tmp_path / 'flags.py'
    evidence = tmp_path / 'flags.json'
    worker.write_text("import sys,json\nfrom pathlib import Path\nPath(" + repr(str(evidence)) +
                     ").write_text(json.dumps({'no_site':sys.flags.no_site,'isolated':sys.flags.isolated}))\n", encoding='ascii')
    monkeypatch.setattr(step_import, '_WORKER', worker)
    runtime = step_import.StepRuntime(Path(sys.executable), tmp_path / 'jobs')
    with pytest.raises(step_import.StepImportError):
        asyncio.run(step_import.import_step(b'ISO-10303-21;HEADER;ENDSEC;DATA;ENDSEC;END-ISO-10303-21;', runtime=runtime))
    assert json.loads(evidence.read_text()) == {'no_site': 1, 'isolated': 1}
