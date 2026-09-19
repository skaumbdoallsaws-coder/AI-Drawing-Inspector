"""Real disk repositories: durable outcomes, ownership, and duplicate dispatch."""
import asyncio
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
import uuid

from ai_inspector.facility_layout.design_brief import design_revision
from ai_inspector.facility_layout.design_repository import FacilityDesignRepository
from ai_inspector.facility_layout.design_service import facility_design_installation_fingerprint
from ai_inspector.facility_layout.facility_draft_lease import FacilityDraftLeaseRepository
from desktop.runtime.profile import RuntimeProfile
from desktop.runtime.transaction_journal import TransactionJournal
from desktop.runtime.boundary import DesktopBoundary


class DesktopRuntimeTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='desktop transaction '); self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.saved = self.data / 'saved-layout.json'; self.saved.write_text('{"saved":"unchanged"}')
        value = {'profileId': 'isolated', 'origin': 'http://127.0.0.1:8198', 'dataRoot': str(self.data),
                 'backendId': str(uuid.uuid4()), 'storeId': str(uuid.uuid4()), 'acceptanceLayoutId': 'fl-isolated'}
        self.profile = RuntimeProfile(value, {'storeBinding': 'b' * 64, 'owner': {'sessionId': 'session-owned', 'ownerId': 'owner-owned'}}, self.data)
        self.journal = self.reopen()

    def reopen(self):
        host = SimpleNamespace(principal=lambda: SimpleNamespace(tenant_id='local', principal_id='principal-local'),
            design_repository=FacilityDesignRepository(self.data / 'design'),
            design_loop_service=SimpleNamespace(lease_repository=FacilityDraftLeaseRepository(self.data / 'leases')))
        return TransactionJournal(self.profile, host, str(uuid.uuid4()))

    def files(self):
        return {str(path.relative_to(self.data)): hashlib.sha256(path.read_bytes()).hexdigest() for path in self.data.rglob('*') if path.is_file()}

    def seed(self, kind='apply'):
        journal = self.journal
        leases, designs = journal.host.design_loop_service.lease_repository, journal.host.design_repository
        lease = leases.acquire(tenant_id='local', site_id='site-local', layout_id='fl-isolated', owner_kind='design_run',
            owner_run_id='run-owned', owner_token='token-owned', base_saved_layout_revision=design_revision('saved'), current_draft_revision=design_revision('draft'))
        frame = {'baseRevision': design_revision('saved'), 'draftRevision': design_revision('draft'),
                 'draftLayout': {'placements': [{'placementId': 'part-a', 'x': 2}]}, 'batches': [{'label': 'edit1'}, {'label': 'edit2'}],
                 'cursor': 2, 'selectedIds': ['part-a'], 'editorGenerationId': 'generation-owned', 'commandJournalHash': design_revision('history'),
                 'activeProposal': {'transactionId': 'tx-owned', 'proposalId': 'proposal-owned',
                                    'proposalRevision': design_revision('proposal'), 'transactionBindingRevision': design_revision('binding')}}
        body = {'transactionId': 'tx-owned', 'designRunId': 'run-owned', 'layoutId': 'fl-isolated', 'status': 'active',
                'updatedAt': leases._now().isoformat(), 'leaseOwnerToken': 'token-owned', 'installedEditorGenerationId': 'generation-owned',
                'proposalBinding': {'resultLayoutRevision': frame['draftRevision']}}
        refs = []
        if kind == 'undo':
            frame.update(activeProposal=None, editorGenerationId='manual-generation')
            ref = {'artifactKind': 'editor_frame', 'artifactId': 'root-frame', 'artifactRevision': design_revision(frame)}
            designs.store_artifact(tenant_id='local', site_id='site-local', artifact_kind=ref['artifactKind'], artifact_id=ref['artifactId'], artifact_revision=ref['artifactRevision'], artifact=frame)
            refs.append(ref); body.update(rootUndoFrameRef=ref, status='undone')
            lease = leases.release(tenant_id='local', site_id='site-local', layout_id='fl-isolated', owner_kind='design_run',
                owner_run_id='run-owned', owner_token='token-owned', expected_lease_revision=lease['leaseRevision'], reason='undo-acknowledged')['lease']
        else:
            active = frame['activeProposal']
            body['expectedInstallationFingerprint'] = facility_design_installation_fingerprint(draft_revision=frame['draftRevision'],
                proposal_id=active['proposalId'], proposal_revision=active['proposalRevision'], transaction_binding_revision=active['transactionBindingRevision'],
                editor_generation_id=frame['editorGenerationId'], command_journal_hash=frame['commandJournalHash'])
        body['leaseRevision'] = lease['leaseRevision']
        envelope = designs.create_transaction(tenant_id='local', site_id='site-local', transaction=body, artifact_refs=refs)
        tracked = {**deepcopy(journal.binding()), 'requestId': 'request-owned', 'kind': kind, 'transactionId': 'tx-owned',
                   'expectedResultEditorGenerationId': 'generation-owned', 'lastSuccessfulTransaction': envelope, 'lastSuccessfulLease': lease,
                   'sourceTransactionId': 'tx-owned' if kind == 'undo' else None, 'rootUndoFrameRef': body.get('rootUndoFrameRef'), 'endpoints': {}}
        journal.write_request('request-owned', tracked)
        return {**deepcopy(journal.binding()), 'requestId': 'request-owned', 'transactionId': 'tx-owned', 'kind': kind,
                'record': {'handleId': 'handle-retained', 'payload': {'snapshot': {'editorFrame': frame}}}}

    def test_reopened_apply_lookup_uses_real_transaction_and_lease_without_writes(self):
        value = self.seed(); before, original = self.files(), deepcopy(value)
        restarted = self.reopen()
        result = restarted.lookup(value)
        self.assertEqual((result['status'], result['outcome']), ('resolved', 'applied'))
        self.assertFalse(result['writeAuthority']); self.assertTrue(result['retainRecoveryHandle'])
        self.assertEqual(result['lookupDiagnostics']['instanceId'], restarted.instance_id)
        self.assertEqual((result['lookupDiagnostics']['transactionReads'], result['lookupDiagnostics']['leaseInspections']), (1, 1))
        self.assertEqual(self.files(), before); self.assertEqual(value, original)

    def test_reopened_undo_requires_exact_manual_history_selection_and_generation(self):
        value = self.seed('undo'); restarted = self.reopen()
        self.assertEqual(restarted.lookup(value)['outcome'], 'undone')
        frame = value['record']['payload']['snapshot']['editorFrame']
        for key, changed in [('selectedIds', []), ('cursor', 1), ('batches', []), ('editorGenerationId', 'wrong')]:
            saved = frame[key]; frame[key] = changed
            before = self.files(); self.assertEqual(restarted.lookup(value)['status'], 'unknown'); self.assertEqual(self.files(), before)
            frame[key] = saved

    def test_expired_lease_and_real_other_writer_do_not_reacquire_or_grant_authority(self):
        value = self.seed()
        leases = self.journal.host.design_loop_service.lease_repository
        original = leases.inspect('local', 'site-local', 'fl-isolated')['lease']
        from datetime import datetime, timedelta
        now = datetime.fromisoformat(original['expiresAt'].replace('Z', '+00:00')) + timedelta(seconds=1)
        leases._clock = lambda: now
        before = self.files(); result = self.journal.lookup(value)
        self.assertEqual(result['status'], 'lease_expired'); self.assertFalse(result['writeAuthority']); self.assertEqual(self.files(), before)
        leases.acquire(tenant_id='local', site_id='site-local', layout_id='fl-isolated', owner_kind='manual_write', owner_run_id='other-writer',
            base_saved_layout_revision=original['baseSavedLayoutRevision'], current_draft_revision=original['currentDraftRevision'])
        before = self.files(); result = self.journal.lookup(value)
        self.assertEqual(result['status'], 'ownership_conflict'); self.assertFalse(result['writeAuthority']); self.assertEqual(self.files(), before)

    def test_unknown_request_and_foreign_identity_cannot_be_bound_from_renderer(self):
        value = self.seed(); before = self.files()
        for changed in [{'requestId': 'unknown'}, {'identity': {'backendId': 'foreign'}}, {'owner': {'sessionId': 'other'}}]:
            result = self.reopen().lookup(dict(value, **changed))
            self.assertEqual(result['status'], 'unknown'); self.assertEqual(result['lookupDiagnostics']['transactionReads'], 0)
        self.assertEqual(self.files(), before)

    def test_dispatch_identity_persists_before_call_and_crash_cannot_redispatch(self):
        path = '/api/facility-layout-design/site-local/fl-isolated/proposals/proposal-owned/apply/prepare'
        value = {'expectedResultEditorGenerationId': 'generation-owned'}
        tracked, replay = self.journal.prepare_dispatch(path, value, 'request-new', 'session-owned')
        self.assertIsNone(replay)
        self.assertEqual(self.reopen().read_request('request-new')['endpoints'][path]['state'], 'dispatching')
        before = self.files()
        with self.assertRaisesRegex(ValueError, 'outcome is unknown'): self.reopen().prepare_dispatch(path, value, 'request-new', 'session-owned')
        self.assertEqual(self.files(), before)

    def test_completed_equivalent_retry_replays_durable_reply_without_execution(self):
        path = '/api/facility-layout-design/site-local/fl-isolated/proposals/proposal-owned/apply/prepare'
        value = {'expectedResultEditorGenerationId': 'generation-owned', 'nested': {'a': 1, 'b': 2}}
        tracked, _ = self.journal.prepare_dispatch(path, value, 'request-new', 'session-owned')
        self.journal.finish_dispatch(path, tracked, 409, {'error': {'code': 'bounded-service-rejection'}})
        reordered = {'nested': {'b': 2, 'a': 1}, 'expectedResultEditorGenerationId': 'generation-owned'}
        before = self.files(); _, replay = self.reopen().prepare_dispatch(path, reordered, 'request-new', 'session-owned')
        self.assertEqual(replay, {'status': 409, 'body': {'error': {'code': 'bounded-service-rejection'}}}); self.assertEqual(self.files(), before)
        with self.assertRaisesRegex(ValueError, 'differs'): self.reopen().prepare_dispatch(path, dict(value, nested={'a': 3}), 'request-new', 'session-owned')

    def test_boundary_records_actual_service_response_and_prevents_second_dispatch(self):
        calls = []
        async def app(scope, receive, send):
            calls.append(scope['path'])
            self.assertEqual(self.journal.read_request('request-new')['endpoints'][scope['path']]['state'], 'dispatching')
            await send({'type': 'http.response.start', 'status': 409, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'{"error":{"code":"service-rejected"}}'})
        boundary = DesktopBoundary(app, self.profile, 'a' * 64, str(uuid.uuid4()), self.journal.host)
        scope = {'type': 'http', 'method': 'POST', 'path': '/api/facility-layout-design/site-local/fl-isolated/proposals/proposal-owned/apply/prepare',
                 'headers': [(b'host', b'127.0.0.1:8198'), (b'x-inspectorpro-desktop-token', b'a' * 64),
                             (b'x-inspectorpro-desktop-request-id', b'request-new'), (b'x-inspectorpro-session', b'session-owned')]}
        async def call():
            async def receive(): return {'type': 'http.request', 'body': b'{"expectedResultEditorGenerationId":"generation-owned"}', 'more_body': False}
            messages = []
            async def send(message): messages.append(message)
            await boundary(scope, receive, send)
            return messages
        first = asyncio.run(call()); second = asyncio.run(call())
        self.assertEqual(len(calls), 1)
        self.assertEqual(next(item['status'] for item in first if item['type'] == 'http.response.start'), 409)
        self.assertEqual(next(item['status'] for item in second if item['type'] == 'http.response.start'), 409)
