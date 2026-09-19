"""Managed restart boundary checks with the real disk transaction/lease stores.

Fresh boundary/repository objects reopen temporary files. No server, Electron,
GPU, provider or application lifespan is started by these unit regressions.
"""
import asyncio
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
import uuid

from ai_inspector.facility_layout.design_brief import design_revision
from ai_inspector.facility_layout.design_repository import FacilityDesignRepository
from ai_inspector.facility_layout.design_service import facility_design_installation_fingerprint
from ai_inspector.facility_layout.facility_draft_lease import FacilityDraftLeaseRepository

SCRIPT = Path(__file__).resolve().parents[1] / 'tools/facility-recovery-backend.py'
spec = importlib.util.spec_from_file_location('managed_recovery_backend_test', SCRIPT)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
LAYOUT = 'fl-managed-isolated'
IDENTITY = {'backendId': 'backend-owned', 'storeId': 'store-owned', 'origin': 'http://127.0.0.1:8199'}
OWNER = {'sessionId': 'session-owned', 'ownerId': 'owner-owned'}
MANAGED_ENV = 'INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS'


class ManagedBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='managed durable recovery ')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.saved = self.root / 'saved-layout.json'
        self.saved.write_bytes(b'{"layout":"original isolated saved bytes"}')
        self.saved_hash = hashlib.sha256(self.saved.read_bytes()).hexdigest()
        self.dispatched = []
        self.boundary = self.make_boundary()

    def make_boundary(self, *, enabled=True, instance=None):
        b = harness.RecoveryBoundary.__new__(harness.RecoveryBoundary)
        b.identity, b.instance_id = deepcopy(IDENTITY), instance or str(uuid.uuid4())
        b.token, b.owner, b.layout_id, b.data = 'a' * 64, deepcopy(OWNER), LAYOUT, self.root
        b.registry_path = self.root / 'recovery-harness-requests.json'
        b.registry = {'requests': {}, 'calls': {}, 'deniedSaveCalls': 0}
        principal = SimpleNamespace(tenant_id='local', principal_id='principal-owned')
        b.host = SimpleNamespace(principal=lambda: principal,
            design_repository=FacilityDesignRepository(self.root / 'design'),
            design_loop_service=SimpleNamespace(lease_repository=FacilityDraftLeaseRepository(self.root / 'lease')))
        with patch.dict(os.environ, {MANAGED_ENV: '1' if enabled else '0'}):
            b.initialize_managed_restart()
        async def app(scope, receive, send):
            self.dispatched.append(scope)
            raise AssertionError('A read-only recovery lookup must never reach application dispatch')
        b.app = app
        b.reload_registry()
        return b

    def seed(self, *, kind='apply', acknowledged=True):
        b = self.boundary
        leases, designs = b.host.design_loop_service.lease_repository, b.host.design_repository
        lease = leases.acquire(tenant_id='local', site_id='site-local', layout_id=LAYOUT,
            owner_kind='design_run', owner_run_id='run-owned', owner_token='token-owned',
            base_saved_layout_revision=design_revision('saved'), current_draft_revision=design_revision('draft'))
        frame = {'baseRevision': design_revision('saved'), 'draftRevision': design_revision('draft'),
                 'draftLayout': {'placements': [{'id': 'placement-a', 'x': 22}]},
                 'batches': [{'operations': [{'type': 'move', 'x': 11}]}, {'operations': [{'type': 'move', 'x': 22}]}],
                 'cursor': 2, 'selectedIds': ['placement-a'], 'editorGenerationId': 'generation-owned',
                 'commandJournalHash': design_revision('two-manual-edits'),
                 'activeProposal': {'transactionId': 'tx-owned', 'proposalId': 'proposal-owned',
                                    'proposalRevision': design_revision('proposal'), 'transactionBindingRevision': design_revision('binding')}}
        body = {'transactionId': 'tx-owned', 'designRunId': 'run-owned', 'layoutId': LAYOUT,
                'status': 'active' if acknowledged else 'committed', 'updatedAt': leases._now().isoformat(),
                'leaseOwnerToken': 'token-owned', 'installedEditorGenerationId': 'generation-owned',
                'proposalBinding': {'resultLayoutRevision': frame['draftRevision']}}
        refs = []
        if kind == 'undo':
            frame['activeProposal'] = None
            frame['editorGenerationId'] = 'generation-before-apply'
            ref = {'artifactKind': 'editor_frame', 'artifactId': 'root-frame', 'artifactRevision': design_revision(frame)}
            designs.store_artifact(tenant_id='local', site_id='site-local', artifact_kind=ref['artifactKind'],
                artifact_id=ref['artifactId'], artifact_revision=ref['artifactRevision'], artifact=frame)
            refs.append(ref)
            body['rootUndoFrameRef'] = ref
            if acknowledged:
                lease = leases.release(tenant_id='local', site_id='site-local', layout_id=LAYOUT,
                    owner_kind='design_run', owner_run_id='run-owned', owner_token='token-owned',
                    expected_lease_revision=lease['leaseRevision'], reason='undo-acknowledged')['lease']
                body['status'] = 'undone'
            else:
                lease = leases.mark_undo_acknowledgment_pending(tenant_id='local', site_id='site-local', layout_id=LAYOUT,
                    owner_run_id='run-owned', owner_token='token-owned', expected_lease_revision=lease['leaseRevision'])
                body['status'] = 'undo_pending'
        else:
            active = frame['activeProposal']
            body['expectedInstallationFingerprint'] = facility_design_installation_fingerprint(
                draft_revision=frame['draftRevision'], proposal_id=active['proposalId'], proposal_revision=active['proposalRevision'],
                transaction_binding_revision=active['transactionBindingRevision'], editor_generation_id=frame['editorGenerationId'],
                command_journal_hash=frame['commandJournalHash'])
        body['leaseRevision'] = lease['leaseRevision']
        transaction = designs.create_transaction(tenant_id='local', site_id='site-local', transaction=body, artifact_refs=refs)
        tracked = {**deepcopy(b.binding()), 'kind': kind, 'transactionId': 'tx-owned',
                   'expectedResultEditorGenerationId': 'generation-owned', 'lastSuccessfulTransaction': transaction,
                   'lastSuccessfulLease': lease, 'sourceTransactionId': 'tx-owned' if kind == 'undo' else None,
                   'rootUndoFrameRef': body.get('rootUndoFrameRef'), 'lastSuccessfulOutcome': 'released' if kind == 'undo' else 'applied'}
        b.registry['requests']['request-owned'] = tracked
        b.registry['calls']['/actual-endpoint/' + kind] = 1
        harness.write_json(b.registry_path, b.registry)
        return {**deepcopy(b.binding()), 'requestId': 'request-owned', 'transactionId': 'tx-owned', 'kind': kind,
                'record': {'handleId': 'retained-recovery-handle', 'payload': {'snapshot': {'editorFrame': deepcopy(frame)}}}}

    def files(self):
        return {str(path.relative_to(self.root)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in self.root.rglob('*') if path.is_file()}

    def fault(self, value, fault):
        return {key: deepcopy(value[key]) for key in ('identity', 'document', 'owner', 'requestId', 'transactionId')} | {'fault': fault}

    async def call(self, b, path, *, method='GET', token=True, value=None, host='127.0.0.1:8199', origin=None):
        headers = [(b'host', host.encode())]
        if token: headers.append((b'x-inspectorpro-recovery-test', b.token.encode()))
        if origin is not None: headers.append((b'origin', origin.encode()))
        scope = {'type': 'http', 'method': method, 'path': path, 'headers': headers, 'query_string': b''}
        async def receive(): return {'type': 'http.request', 'body': json.dumps(value or {}).encode(), 'more_body': False}
        messages = []
        async def send(message): messages.append(message)
        await b(scope, receive, send)
        status = next(message['status'] for message in messages if message['type'] == 'http.response.start')
        body = json.loads(b''.join(message.get('body', b'') for message in messages if message['type'] == 'http.response.body'))
        return status, body

    def assert_read_only(self, b, value, expected):
        original_value, before = deepcopy(value), self.files()
        result = b.transaction(value)
        self.assertEqual(result['status'], expected)
        self.assertEqual(value, original_value, 'The retained handle, draft, selection and history must not change')
        self.assertEqual(self.files(), before, 'Lookup must not rewrite a transaction, lease, registry or saved layout')
        self.assertFalse(result['writeAuthority'])
        self.assertTrue(result['retainRecoveryHandle'])
        self.assertEqual(result['recoveryRequired'], expected != 'resolved')
        diagnostics = result['lookupDiagnostics']
        self.assertEqual((diagnostics['instanceId'], diagnostics['transactionReads'], diagnostics['leaseInspections']), (b.instance_id, 1, 1))
        self.assertTrue(diagnostics['readOnly'])
        self.assertTrue(diagnostics['registryReloaded'])
        self.assertEqual(diagnostics['applicationDispatches'], 0)
        self.assertEqual(self.dispatched, [])
        self.assertEqual(b.registry['deniedSaveCalls'], 0)
        self.assertEqual(hashlib.sha256(self.saved.read_bytes()).hexdigest(), self.saved_hash)
        return result

    def test_restart_runtime_keeps_binding_and_changes_only_process_instance_identity(self):
        value = self.seed()
        restarted = self.make_boundary()
        self.assertEqual(restarted.binding(), self.boundary.binding())
        self.assertNotEqual(restarted.runtime()['instanceId'], self.boundary.runtime()['instanceId'])
        self.assertEqual(restarted.runtime()['origin'], IDENTITY['origin'])
        self.assertEqual(restarted.runtime()['processId'], os.getpid())
        self.assertNotIn('token', restarted.runtime())
        self.assert_read_only(restarted, value, 'resolved')

    def test_durable_apply_reopens_real_repositories_and_ignores_stale_memory(self):
        value = self.seed()
        restarted = self.make_boundary()
        restarted.registry['requests'].clear()
        self.assertIsNot(restarted.host.design_repository, self.boundary.host.design_repository)
        result = self.assert_read_only(restarted, value, 'resolved')
        self.assertEqual(result['outcome'], 'applied')
        self.assertEqual(result['lookupDiagnostics']['transactionCalls'], {'/actual-endpoint/apply': 1})

    def test_durable_undo_accepts_real_released_lease_and_exact_root_frame(self):
        value = self.seed(kind='undo')
        restarted = self.make_boundary()
        result = self.assert_read_only(restarted, value, 'resolved')
        self.assertEqual(result['outcome'], 'undone')
        self.assertEqual(result['lease']['status'], 'released')
        self.assertEqual(result['lookupDiagnostics']['artifactReads'], 1)
        frame = value['record']['payload']['snapshot']['editorFrame']
        for key, altered in [('selectedIds', []), ('cursor', 1), ('batches', []), ('draftLayout', {}),
                             ('editorGenerationId', 'other-generation'), ('commandJournalHash', design_revision('other-journal'))]:
            original = frame[key]
            frame[key] = altered
            self.assert_read_only(restarted, value, 'unknown')
            frame[key] = original

    def check_expiry(self, kind):
        value = self.seed(kind=kind, acknowledged=False)
        before_lease = self.boundary.host.design_loop_service.lease_repository.lease_path('local', 'site-local', LAYOUT).read_bytes()
        injected = self.boundary.lease_fault(self.fault(value, 'expire'))
        self.assertTrue(injected['ownership']['expired'])
        self.assertFalse(injected['ownership']['active'])
        self.assertEqual(self.boundary.host.design_loop_service.lease_repository.lease_path('local', 'site-local', LAYOUT).read_bytes(), before_lease)
        restarted = self.make_boundary()
        result = self.assert_read_only(restarted, value, 'lease_expired')
        self.assertEqual(result['transactionId'], value['transactionId'])
        self.assertEqual(restarted.host.design_loop_service.lease_repository.inspect('local', 'site-local', LAYOUT)['lease'], injected['lease'])

    def test_pending_apply_expiry_survives_reopen_without_lease_renewal(self):
        self.check_expiry('apply')

    def test_pending_undo_expiry_survives_reopen_without_lease_renewal(self):
        self.check_expiry('undo')

    def check_takeover(self, kind):
        value = self.seed(kind=kind, acknowledged=False)
        original = self.boundary.registry['requests']['request-owned']['lastSuccessfulLease']
        injected = self.boundary.lease_fault(self.fault(value, 'takeover'))
        self.assertTrue(injected['ownership']['active'])
        self.assertEqual(injected['lease']['ownerKind'], 'manual_write')
        self.assertNotEqual(injected['lease']['ownerToken'], original['ownerToken'])
        restarted = self.make_boundary()
        self.assert_read_only(restarted, value, 'ownership_conflict')
        self.assertEqual(restarted.host.design_loop_service.lease_repository.inspect('local', 'site-local', LAYOUT)['lease'], injected['lease'])
        # A second lookup cannot silently acquire, renew or release either lease.
        self.assert_read_only(restarted, value, 'ownership_conflict')

    def test_pending_apply_other_writer_is_real_acquire_and_stays_owner(self):
        self.check_takeover('apply')

    def test_pending_undo_other_writer_is_real_acquire_and_stays_owner(self):
        self.check_takeover('undo')

    def test_new_controls_are_absent_without_explicit_managed_environment(self):
        self.seed()
        disabled = self.make_boundary(enabled=False)
        for path, method in [('/__facility-recovery__/runtime', 'GET'), ('/__facility-recovery__/lease-fault', 'POST')]:
            status, body = asyncio.run(self.call(disabled, path, method=method))
            self.assertEqual(status, 403)
            self.assertEqual(body['error']['code'], 'harness_route_denied')
        self.assertFalse(hasattr(disabled, 'clock_path'))

    def test_runtime_and_fault_require_credential_exact_host_and_same_origin(self):
        value = self.seed(acknowledged=False)
        before = self.files()
        for path, method in [('/__facility-recovery__/runtime', 'GET'), ('/__facility-recovery__/lease-fault', 'POST')]:
            for kwargs in [{'token': False}, {'host': 'foreign.example'}, {'origin': 'http://foreign.example'}]:
                status, body = asyncio.run(self.call(self.boundary, path, method=method, value=self.fault(value, 'takeover'), **kwargs))
                self.assertEqual(status, 403)
                self.assertEqual(body['error']['code'], 'isolated_recovery_harness_required')
        self.assertEqual(self.files(), before)

    def test_foreign_identity_owner_request_or_transaction_cannot_inject_fault(self):
        value = self.seed(acknowledged=False)
        original = self.fault(value, 'takeover')
        before = self.files()
        for key, altered in [('identity', {'backendId': 'unrelated'}), ('document', {'documentId': 'different'}),
                             ('owner', {'ownerId': 'different'}), ('requestId', 'unknown'), ('transactionId', 'unknown'), ('fault', 'arbitrary')]:
            with self.subTest(key=key):
                changed = dict(original, **{key: altered})
                status, _ = asyncio.run(self.call(self.boundary, '/__facility-recovery__/lease-fault', method='POST', value=changed))
                self.assertEqual(status, 409)
                self.assertEqual(self.files(), before)

    def test_changed_durable_identity_cannot_be_rebound_from_renderer_handle(self):
        value = self.seed()
        restarted = self.make_boundary()
        restarted.identity['storeId'] = 'foreign-store'
        before = self.files()
        result = restarted.transaction(value)
        self.assertEqual(result['status'], 'unknown')
        self.assertFalse(result['writeAuthority'])
        self.assertTrue(result['recoveryRequired'])
        self.assertEqual(result['lookupDiagnostics']['transactionReads'], 0)
        self.assertEqual(result['lookupDiagnostics']['leaseInspections'], 0)
        self.assertEqual(self.files(), before)

    def test_lookup_evidence_records_new_instance_and_never_changes_endpoint_counts(self):
        value = self.seed()
        restarted = self.make_boundary()
        self.assert_read_only(restarted, value, 'resolved')
        status, evidence = asyncio.run(self.call(restarted, '/__facility-recovery__/evidence'))
        self.assertEqual(status, 200)
        self.assertEqual(evidence['runtime']['instanceId'], restarted.instance_id)
        self.assertEqual(evidence['lookups'][0]['instanceId'], restarted.instance_id)
        self.assertEqual(evidence['calls'], {'/actual-endpoint/apply': 1})
        self.assertEqual(evidence['deniedSaveCalls'], 0)


if __name__ == '__main__':
    unittest.main()
