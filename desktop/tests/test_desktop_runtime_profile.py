import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import uuid

from desktop.runtime.profile import MARKER, prepare_profile, read_json
from desktop.runtime.managed_backend import PrivateControl, bootstrap


class DesktopRuntimeProfileTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop profile ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.app = self.root / 'app'; self.app.mkdir()
        self.data = self.root / 'data'
        self.value = {'schemaVersion': 1, 'mode': 'managed', 'profileId': 'isolated', 'origin': 'http://127.0.0.1:8198',
                      'dataRoot': str(self.data), 'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4()), 'acceptanceLayoutId': None}

    def test_stable_profile_root_identity_and_owner_reopen_exactly(self):
        first = prepare_profile(self.value, self.app)
        second = prepare_profile(self.value, self.app)
        self.assertEqual(first.marker, second.marker)
        self.assertEqual(first.owner, second.owner)
        a, b = first.identity(str(uuid.uuid4())), second.identity(str(uuid.uuid4()))
        self.assertNotEqual(a.pop('instanceId'), b.pop('instanceId')); self.assertEqual(a, b)
        self.assertEqual(first.capabilities, {'generalEditing': False, 'researchBrowsing': False, 'facilityAcceptance': False})
        self.assertNotIn('credential', json.dumps(read_json(self.data / MARKER)))

    def test_profile_retargeting_or_identity_change_cannot_reuse_store(self):
        prepare_profile(self.value, self.app)
        for key, altered in [('backendId', str(uuid.uuid4())), ('storeId', str(uuid.uuid4())), ('profileId', 'other'), ('origin', 'http://127.0.0.1:8199')]:
            with self.subTest(key=key), self.assertRaises(ValueError): prepare_profile(dict(self.value, **{key: altered}), self.app)

    def test_marker_copy_does_not_transfer_authoritative_store_identity(self):
        prepare_profile(self.value, self.app)
        other = self.root / 'other'; other.mkdir()
        (other / MARKER).write_bytes((self.data / MARKER).read_bytes())
        with self.assertRaises(ValueError): prepare_profile(dict(self.value, dataRoot=str(other)), self.app)

    def test_existing_unmarked_data_cannot_be_adopted(self):
        self.data.mkdir(); (self.data / 'actual-layout.json').write_text('{}')
        with self.assertRaises(ValueError): prepare_profile(self.value, self.app)
        self.assertFalse((self.data / MARKER).exists())

    def test_acceptance_requires_marked_copy_and_exact_saved_bytes(self):
        self.data.mkdir()
        layout = self.data / 'facility/layouts/local/site-local/layouts/fl-isolated.json'; layout.parent.mkdir(parents=True); layout.write_text('{"layout":1}')
        manifest = {'fixtureRoot': str(self.data), 'source': {'root': str(self.root / 'live-source')},
                    'layout': {'layoutId': 'fl-isolated', 'relativePath': str(layout.relative_to(self.data)), 'revision': hashlib.sha256(layout.read_bytes()).hexdigest()}}
        (self.data / 'facility-recovery-fixture.json').write_text(json.dumps(manifest))
        value = dict(self.value, acceptanceLayoutId='fl-isolated')
        profile = prepare_profile(value, self.app)
        self.assertTrue(profile.capabilities['facilityAcceptance'])
        layout.write_text('{"layout":2}')
        with self.assertRaises(ValueError): prepare_profile(value, self.app)

    def test_rejects_remote_origin_credentials_extra_fields_and_path_overlap(self):
        for patch in [{'origin': 'https://127.0.0.1:8198'}, {'origin': 'http://localhost:8198'},
                      {'origin': 'http://a:b@127.0.0.1:8198'}, {'origin': 'http://127.0.0.1:8198/path'},
                      {'credential': 'a' * 64}, {'dataRoot': str(self.app)}, {'schemaVersion': True}]:
            with self.subTest(patch=patch), self.assertRaises(ValueError): prepare_profile(dict(self.value, **patch), self.app)

    def test_private_bootstrap_has_closed_schema_and_no_argv_or_environment_fallback(self):
        value = {'schemaVersion': 1, 'credential': 'a' * 64, 'instanceId': str(uuid.uuid4())}
        self.assertEqual(bootstrap(io.BytesIO((json.dumps(value) + '\n').encode())), value)
        for raw in [b'', b'{}\n', json.dumps(value).encode(), (json.dumps(dict(value, unexpected='x')) + '\n').encode(), b'x' * 5000]:
            with self.subTest(length=len(raw)), self.assertRaisesRegex(ValueError, '^A valid private desktop launch handshake is required$'):
                bootstrap(io.BytesIO(raw))

    def test_private_shutdown_and_eof_request_only_owned_runtime_stop(self):
        request_id = str(uuid.uuid4())
        control = PrivateControl(io.BytesIO((json.dumps({'schemaVersion': 1, 'command': 'shutdown', 'requestId': request_id}) + '\n').encode()))
        control.read(); self.assertTrue(control.stop.is_set()); self.assertEqual(control.request_id, request_id); self.assertFalse(control.invalid)
        ended = PrivateControl(io.BytesIO()); ended.read(); self.assertEqual(ended.reason, 'private-channel-eof')
        malformed = PrivateControl(io.BytesIO(b'{"command":"stop-other-server"}\n'))
        malformed.read(); self.assertTrue(malformed.invalid); self.assertEqual(malformed.reason, 'invalid-private-control')
