"""Offline seed uses real facility previews/artifacts and never invokes Save."""
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch
import uuid

from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
from desktop.runtime.profile import prepare_profile

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/seed-runtime-proposal.py'
spec = importlib.util.spec_from_file_location('runtime_seed_test', SCRIPT)
seeder = importlib.util.module_from_spec(spec); spec.loader.exec_module(seeder)


class DesktopRuntimeSeedTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop offline proposal ', delete=False)
        self.addCleanup(self.cleanup_owned_directory)
        self.root = Path(self.temp.name); self.data = self.root / 'data'; self.app = self.root / 'app'; self.app.mkdir()
        self.host = LocalFacilityLayoutHost(self.data / 'facility'); self.addCleanup(self.host.close)
        initial = self.host.ensure_bootstrap()['layout']['layout']
        document = deepcopy(initial); document['layoutId'] = 'fl-isolated'
        document['zones'] = [{'zoneId': 'zn-isolated', 'zoneType': 'staging', 'label': 'Receiving',
            'boundary': [{'x': 1, 'z': 1}, {'x': 4, 'z': 1}, {'x': 4, 'z': 3}, {'x': 1, 'z': 3}],
            'floorElevation': 0, 'anchors': [], 'evidence': []}]
        self.host.service.create_layout(self.host.principal(), 'site-local', document)
        self.saved = next(self.data.rglob('fl-isolated.json'))
        manifest = {'fixtureRoot': str(self.data), 'source': {'root': str(self.root / 'live-source')},
                    'layout': {'layoutId': 'fl-isolated', 'relativePath': str(self.saved.relative_to(self.data)), 'revision': hashlib.sha256(self.saved.read_bytes()).hexdigest()}}
        (self.data / 'facility-recovery-fixture.json').write_text(json.dumps(manifest))
        self.value = {'schemaVersion': 1, 'mode': 'managed', 'profileId': 'seed-isolated', 'origin': 'http://127.0.0.1:8198',
                      'dataRoot': str(self.data), 'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4()), 'acceptanceLayoutId': 'fl-isolated'}
        self.profile = prepare_profile(self.value, self.app)

    def cleanup_owned_directory(self):
        # Real design artifact paths can exceed MAX_PATH. Verify this exact
        # test-owned root before recursive cleanup using extended local spelling.
        selected = Path(self.temp.name).resolve()
        if selected.parent != Path(tempfile.gettempdir()).resolve() or not selected.name.startswith('desktop offline proposal '):
            raise RuntimeError('Refusing cleanup outside the exact test temporary directory')
        shutil.rmtree('\\\\?\\' + str(selected) if os.name == 'nt' else selected)

    def files(self):
        data = Path('\\\\?\\' + str(self.data)) if os.name == 'nt' else self.data
        return {str(path.relative_to(data)): hashlib.sha256(path.read_bytes()).hexdigest() for path in data.rglob('*') if path.is_file()}

    def test_seed_uses_real_kernel_and_exact_service_artifacts_without_save_or_compiler(self):
        before = self.saved.read_bytes()
        with patch.object(self.host.service, 'save_layout', side_effect=AssertionError('Save forbidden')) as save, patch('subprocess.Popen', side_effect=AssertionError('No provider or compiler')):
            result = seeder.seed_proposal(self.profile, self.host)
        save.assert_not_called()
        self.assertEqual(result['labels']['edit1'], 'Receiving [desktop edit 1]')
        self.assertEqual(result['labels']['edit2'], 'Receiving [desktop edit 2]')
        self.assertEqual(result['zoneId'], 'zn-isolated')
        self.assertEqual(before, self.saved.read_bytes())
        self.assertEqual(result['savedLayoutSha256Before'], result['savedLayoutSha256After'])
        proposal = self.host.design_repository.get_artifact('local', 'site-local', 'design_proposal', result['proposal']['proposalId'], result['proposal']['proposalRevision'])['artifact']
        ref = proposal['candidateRef']
        candidate = self.host.design_repository.get_artifact('local', 'site-local', ref['artifactKind'], ref['artifactId'], ref['artifactRevision'])['artifact']
        self.assertEqual(candidate['candidateLayout']['zones'][0]['label'], result['labels']['apply'])
        self.assertEqual(candidate['resultLayoutRevision'], result['resultLayoutRevision'])
        self.assertEqual(candidate['operations'], [{'op': 'edit_zone', 'zoneId': 'zn-isolated', 'patch': {'label': result['labels']['apply']}}])
        self.assertEqual(json.loads((self.data / 'runtime-proposal.json').read_text()), result)
        self.assertEqual((result['providerCalls'], result['saveCalls'], result['plannerAcceptance']), (0, 0, False))

    def test_seed_cannot_replace_an_existing_reference_or_create_more_artifacts(self):
        seeder.seed_proposal(self.profile, self.host)
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'already exists'): seeder.seed_proposal(self.profile, self.host)
        after = self.files()
        self.assertEqual(before, after)

    def test_changed_saved_bytes_fail_before_proposal_creation(self):
        self.saved.write_bytes(self.saved.read_bytes() + b' ')
        with self.assertRaisesRegex(ValueError, 'provenance changed'): seeder.seed_proposal(self.profile, self.host)
        self.assertFalse((self.data / 'runtime-proposal.json').exists())
