"""Read-only ASGI boundary and backend-owned recovery lookup checks.

Tests use only in-memory repositories, temporary registry files and ASGI calls;
no server, provider, native helper or Electron is started.
"""
import asyncio
from copy import deepcopy
import importlib.util
import hashlib
import json
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import Mock, patch

SCRIPT = Path(__file__).resolve().parents[1] / "tools/facility-recovery-backend.py"
spec = importlib.util.spec_from_file_location("facility_recovery_backend_test", SCRIPT)
harness = importlib.util.module_from_spec(spec)
spec.loader.exec_module(harness)
LAYOUT = "fl-reference-manual-20260812"
BASE = "/api/facility-layout-design/site-local/" + LAYOUT


class RecoveryBackendTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="recovery boundary ")
        self.boundary = harness.RecoveryBoundary.__new__(harness.RecoveryBoundary)
        b = self.boundary
        b.identity = {"schemaVersion": 1, "product": "InspectorPro", "mode": "rendering-spike",
                      "backendId": "backend-isolated", "storeId": "store-isolated", "profileId": "test",
                      "origin": "http://127.0.0.1:8199", "researchBrowsing": False, "interactive": False}
        b.instance_id = "instance-fixture"
        b.token = "a" * 64
        b.owner = {"sessionId": "session-owned", "ownerId": "owner-owned"}
        b.layout_id = LAYOUT
        b.data = Path(self.temp.name)
        b.registry_path = b.data / "requests.json"
        b.registry = {"requests": {}, "calls": {}, "deniedSaveCalls": 0}
        self.principal = SimpleNamespace(tenant_id="local", principal_id="principal-owned")
        self.transaction = {"transactionId": "tx-owned", "layoutId": LAYOUT, "status": "active",
                            "designRunId": "run-owned", "leaseOwnerToken": "token-owned",
                            "leaseRevision": "lease-revision-owned", "installedEditorGenerationId": "generation-owned",
                            "proposalBinding": {"resultLayoutRevision": "draft-owned"}}
        self.envelope = {"transaction": self.transaction, "transactionRevision": "transaction-revision-owned"}
        self.lease = {"ownerKind": "design_run", "ownerRunId": "run-owned", "ownerToken": "token-owned",
                      "status": "active", "leaseRevision": "lease-revision-owned", "currentDraftRevision": "draft-owned"}
        self.ownership = {"active": True, "expired": False, "lease": self.lease}
        self.frame = {"editorGenerationId": "generation-owned", "draftRevision": "draft-owned", "commandJournalHash": "journal-owned",
                      "activeProposal": {"transactionId": "tx-owned", "proposalId": "proposal-owned",
                                         "proposalRevision": "proposal-revision-owned", "transactionBindingRevision": "binding-owned"}}
        def fingerprint(**kwargs):
            return hashlib.sha256(json.dumps(kwargs, sort_keys=True).encode()).hexdigest()
        self.fingerprint = fingerprint
        self.transaction['expectedInstallationFingerprint'] = fingerprint(draft_revision='draft-owned', proposal_id='proposal-owned',
            proposal_revision='proposal-revision-owned', transaction_binding_revision='binding-owned', editor_generation_id='generation-owned', command_journal_hash='journal-owned')
        self.fingerprint_patch = patch.dict(sys.modules, {'ai_inspector.facility_layout.design_service': SimpleNamespace(facility_design_installation_fingerprint=fingerprint)})
        self.fingerprint_patch.start()
        self.addCleanup(self.fingerprint_patch.stop)
        b.host = SimpleNamespace(principal=lambda: self.principal,
            design_repository=SimpleNamespace(get_transaction=Mock(side_effect=lambda *args: deepcopy(self.envelope))),
            design_loop_service=SimpleNamespace(lease_repository=SimpleNamespace(inspect=Mock(side_effect=lambda *args: deepcopy(self.ownership)))))
        self.app_calls = []
        async def app(scope, receive, send):
            self.app_calls.append(scope)
            if scope['type'] == 'lifespan':
                return
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b'{"ok":true}'})
        b.app = app

    def tearDown(self):
        self.temp.cleanup()

    def tracked(self, kind="apply"):
        self.boundary.registry["requests"]["request-owned"] = {
            **deepcopy(self.boundary.binding()), "kind": kind, "transactionId": "tx-owned",
            "expectedResultEditorGenerationId": "generation-owned",
            "lastSuccessfulTransaction": deepcopy(self.envelope), "lastSuccessfulLease": deepcopy(self.lease),
            "sourceTransactionId": "tx-owned" if kind == 'undo' else None,
            "rootUndoFrameRef": deepcopy(self.transaction.get('rootUndoFrameRef')),
            "responses": [{"path": BASE + "/transactions/tx-owned/apply/acknowledge", "status": 200,
                           "transactionRevision": "transaction-revision-owned"}]}
        return dict(self.boundary.binding(), requestId="request-owned", transactionId="tx-owned", kind=kind,
                    record={'payload': {'snapshot': {'editorFrame': deepcopy(self.frame)}}})

    async def call(self, path="/", *, method="GET", token=True, origin=None, host="127.0.0.1:8199", value=None, headers=(), session=True):
        scope = {"type": "http", "method": method, "path": path, "query_string": b"", "headers": [(b"host", host.encode()), *headers]}
        if token:scope["headers"].append((b"x-inspectorpro-recovery-test", self.boundary.token.encode()))
        if session:scope['headers'].append((b'x-inspectorpro-session', self.boundary.owner['sessionId'].encode()))
        if origin is not None:scope["headers"].append((b"origin", origin.encode()))
        body = json.dumps(value or {}).encode()
        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}
        messages = []
        async def send(message):messages.append(message)
        await self.boundary(scope, receive, send)
        response = next(x for x in messages if x["type"] == "http.response.start")
        data = b"".join(x.get("body", b"") for x in messages if x["type"] == "http.response.body")
        return response["status"], json.loads(data or b"{}"), response.get("headers", [])

    def test_read_methods_only_target_layout_and_known_assets(self):
        for path in ("/", "/static/index.js", "/generated/industrial_assets/model.glb", "/api/industrial-assets",
                     "/api/facility-layouts/site-local/" + LAYOUT):
            self.assertTrue(harness.permitted("GET", path, LAYOUT), path)
        for path in ("/api/bridge/status", "/api/admin/memory/health", "/api/facility-layouts/site-local/fl-other",
                     "/generated/../secret", "/static/..\\secret"):
            self.assertFalse(harness.permitted("GET", path, LAYOUT), path)

    def test_only_narrow_transaction_posts_are_permitted(self):
        for suffix in ("proposals/proposal-owned/apply/prepare", "transactions/tx-owned/apply/commit",
                       "transactions/tx-owned/apply/acknowledge", "transactions/tx-owned/apply/recover",
                       "transactions/tx-owned/undo/prepare", "transactions/tx-owned/undo/acknowledge"):
            self.assertTrue(harness.permitted("POST", BASE + "/" + suffix, LAYOUT))
        for method, path in (("PUT", "/api/facility-layouts/site-local/" + LAYOUT),
                             ("POST", "/api/agent/chat"), ("POST", BASE + "/save"),
                             ("DELETE", "/api/facility-layouts/site-local/" + LAYOUT),
                             ("POST", BASE + "/transactions/tx-owned/undo/commit"),
                             ("POST", BASE.replace(LAYOUT, "fl-other") + "/transactions/tx-owned/apply/commit")):
            self.assertFalse(harness.permitted(method, path, LAYOUT))

    def test_missing_token_wrong_host_or_cross_origin_never_reaches_application(self):
        for kwargs in ({"token": False}, {"host": "evil.invalid"}, {"origin": "http://evil.invalid"}):
            status, body, _ = asyncio.run(self.call(**kwargs))
            self.assertEqual(status, 403)
            self.assertEqual(body["error"]["code"], "isolated_recovery_harness_required")
        self.assertEqual(self.app_calls, [])

    def test_identity_is_public_only_on_exact_loopback_host_and_origin(self):
        status, body, headers = asyncio.run(self.call(harness.base.IDENTITY_PATH, token=False))
        self.assertEqual(status, 200)
        self.assertEqual(body["storeId"], "store-isolated")
        self.assertNotIn("origin", body)
        self.assertNotIn("token", body)
        self.assertEqual(dict(headers)[b"x-inspectorpro-rendering-instance"], b"instance-fixture")
        status, _, _ = asyncio.run(self.call(harness.base.IDENTITY_PATH, token=False, host="evil.invalid"))
        self.assertEqual(status, 403)
        self.assertEqual(self.app_calls, [])

    def test_save_attempt_is_denied_and_counted_without_reaching_application(self):
        status, body, _ = asyncio.run(self.call("/api/facility-layouts/site-local/" + LAYOUT, method="PUT"))
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "facility_recovery_operation_denied")
        self.assertEqual(json.loads(self.boundary.registry_path.read_text())["deniedSaveCalls"], 1)
        self.assertEqual(self.app_calls, [])

    def test_unknown_custom_route_and_missing_transaction_request_id_are_denied(self):
        status, _, _ = asyncio.run(self.call("/__facility-recovery__/not-a-route"))
        self.assertEqual(status, 403)
        status, body, _ = asyncio.run(self.call(BASE + "/transactions/tx-owned/apply/commit", method="POST"))
        self.assertEqual(status, 403)
        self.assertEqual(body["error"]["code"], "harness_request_identity_required")
        self.assertEqual(self.app_calls, [])

    def test_websocket_denied_and_lifespan_delegated(self):
        messages = []
        async def send(message):messages.append(message)
        asyncio.run(self.boundary({"type": "websocket"}, None, send))
        self.assertEqual(messages, [{"type": "websocket.close", "code": 1008}])
        asyncio.run(self.boundary({"type": "lifespan"}, None, send))
        self.assertEqual(self.app_calls, [{"type": "lifespan"}])

    def test_unknown_request_or_foreign_owner_never_reads_transaction_repository(self):
        value = self.tracked()
        for changed in ({"requestId": "unknown"}, {"owner": {"ownerId": "different", "sessionId": "different"}},
                        {"identity": {"backendId": "live", "storeId": "live"}},
                        {"document": {"tenantId": "different"}}, {"kind": "undo"}, {"transactionId": "different"}):
            result = self.boundary.transaction(dict(value, **changed))
            self.assertEqual(result["status"], "unknown")
        self.boundary.host.design_repository.get_transaction.assert_not_called()

    def test_recorded_request_real_transaction_and_active_owned_lease_resolve_apply(self):
        result = self.boundary.transaction(self.tracked())
        self.assertEqual((result["status"], result["outcome"]), ("resolved", "applied"))
        self.boundary.host.design_repository.get_transaction.assert_called_once_with("local", "site-local", "tx-owned")
        self.boundary.host.design_loop_service.lease_repository.inspect.assert_called_once_with("local", "site-local", LAYOUT)

    def test_other_layout_or_foreign_lease_owner_cannot_resolve(self):
        value = self.tracked()
        self.transaction["layoutId"] = "fl-other"
        self.assertEqual(self.boundary.transaction(value)["status"], "unknown")
        self.transaction["layoutId"] = LAYOUT
        for field in ("ownerRunId", "ownerToken", "ownerKind"):
            original = self.lease[field];self.lease[field] = "foreign"
            self.assertEqual(self.boundary.transaction(value)["status"], "unknown")
            self.lease[field] = original

    def test_expired_or_inactive_matching_lease_cannot_resolve_apply(self):
        value = self.tracked()
        self.ownership.update(active=False, expired=True)
        self.assertEqual(self.boundary.transaction(value)["status"], "unknown")

    def test_changed_lease_revision_or_draft_cannot_resolve_apply(self):
        value = self.tracked()
        for field in ("leaseRevision", "currentDraftRevision"):
            original = self.lease[field];self.lease[field] = "changed"
            self.assertEqual(self.boundary.transaction(value)["status"], "unknown")
            self.lease[field] = original

    def test_changed_installed_generation_cannot_resolve_apply(self):
        value = self.tracked()
        self.transaction["installedEditorGenerationId"] = "generation-foreign"
        self.assertEqual(self.boundary.transaction(value)["status"], "unknown")


    def test_unrecorded_generation_and_changed_retained_binding_are_unknown(self):
        value = self.tracked()
        record = self.boundary.registry['requests']['request-owned']
        record.pop('expectedResultEditorGenerationId')
        self.assertEqual(self.boundary.transaction(value)['status'], 'unknown')
        self.boundary.host.design_repository.get_transaction.assert_not_called()
        record['expectedResultEditorGenerationId'] = 'generation-owned'
        record['identity']['storeId'] = 'foreign-store'
        self.assertEqual(self.boundary.transaction(value)['status'], 'unknown')

    def test_frame_fingerprint_and_generation_must_match_real_retained_transaction(self):
        value = self.tracked()
        frame = value['record']['payload']['snapshot']['editorFrame']
        for field, changed in [('commandJournalHash', 'different'), ('draftRevision', 'different'), ('editorGenerationId', 'different')]:
            original = frame[field];frame[field] = changed
            self.assertEqual(self.boundary.transaction(value)['status'], 'unknown')
            frame[field] = original

    def test_released_lease_and_exact_root_frame_resolve_acknowledged_undo(self):
        ref = {'artifactKind': 'editor_frame', 'artifactId': 'root-frame', 'artifactRevision': 'root-revision'}
        self.transaction.update(status='undone', rootUndoFrameRef=ref)
        self.lease['status'] = 'released';self.ownership.update(active=False, expired=True)
        self.frame = {'baseRevision': 'saved-base', 'draftRevision': 'root-draft', 'draftLayout': {'placements': []},
                      'batches': [], 'cursor': 0, 'selectedIds': [], 'editorGenerationId': 'root-generation', 'commandJournalHash': 'root-journal'}
        self.boundary.host.design_repository.get_artifact = Mock(return_value={'artifact': deepcopy(self.frame)})
        value = self.tracked('undo')
        result = self.boundary.transaction(value)
        self.assertEqual((result['status'], result['outcome']), ('resolved', 'undone'))
        value['record']['payload']['snapshot']['editorFrame']['cursor'] = 1
        self.assertEqual(self.boundary.transaction(value)['status'], 'unknown')
        self.ownership['active'] = True
        self.assertEqual(self.boundary.transaction(self.tracked('undo'))['status'], 'unknown')

    def test_undo_return_to_prior_owner_requires_real_retained_outcome(self):
        self.transaction.update(status='undone', rootUndoFrameRef={'artifactKind': 'editor_frame', 'artifactId': 'root', 'artifactRevision': 'root-rev'})
        self.lease.update(ownerRunId='prior-run', ownerToken='prior-token', ownerKind='generation_run')
        self.boundary.host.design_repository.get_artifact = Mock(return_value={'artifact': deepcopy(self.frame)})
        value = self.tracked('undo')
        self.assertEqual(self.boundary.transaction(value)['status'], 'unknown')
        self.boundary.registry['requests']['request-owned']['lastSuccessfulOutcome'] = 'returned_to_prior_owner'
        self.assertEqual(self.boundary.transaction(value)['outcome'], 'undone')
        self.lease['ownerToken'] = 'a-third-owner'
        self.assertEqual(self.boundary.transaction(value)['status'], 'unknown')

    def test_prepare_binding_is_persisted_before_dispatch_and_response_bound(self):
        path = BASE + '/proposals/proposal-owned/apply/prepare'
        async def application(scope, receive, send):
            saved = json.loads(self.boundary.registry_path.read_text())['requests']['request-new']
            self.assertEqual(saved['expectedResultEditorGenerationId'], 'generation-owned')
            self.assertEqual(saved['identity'], self.boundary.binding()['identity'])
            self.assertNotIn('lastSuccessfulTransaction', saved)
            await send({'type': 'http.response.start', 'status': 200, 'headers': []})
            await send({'type': 'http.response.body', 'body': json.dumps({'transaction': self.envelope, 'lease': self.lease}).encode()})
        self.boundary.app = application
        status, _, _ = asyncio.run(self.call(path, method='POST', value={'expectedResultEditorGenerationId': 'generation-owned'},
                                             headers=[(b'x-inspectorpro-recovery-request', b'request-new')]))
        self.assertEqual(status, 200)
        tracked = self.boundary.registry['requests']['request-new']
        self.assertEqual(tracked['lastSuccessfulTransaction'], self.envelope)
        self.assertEqual(tracked['lastSuccessfulLease'], self.lease)
        self.assertEqual(tracked['transactionId'], 'tx-owned')
        status, _, _ = asyncio.run(self.call(BASE + '/proposals/second-proposal/apply/prepare', method='POST',
                                             value={'expectedResultEditorGenerationId': 'generation-owned'},
                                             headers=[(b'x-inspectorpro-recovery-request', b'request-new')]))
        self.assertEqual(status, 409)
        status, _, _ = asyncio.run(self.call(path, method='POST', value={'expectedResultEditorGenerationId': 'different-generation'},
                                             headers=[(b'x-inspectorpro-recovery-request', b'request-new')]))
        self.assertEqual(status, 409)

    def test_undo_first_request_records_real_source_transaction_before_dispatch(self):
        ref = {'artifactKind': 'editor_frame', 'artifactId': 'root', 'artifactRevision': 'root-rev'}
        self.transaction['rootUndoFrameRef'] = ref
        async def application(scope, receive, send):
            saved = json.loads(self.boundary.registry_path.read_text())['requests']['undo-new']
            self.assertEqual(saved['sourceTransactionId'], 'tx-owned')
            self.assertEqual(saved['sourceTransactionRevision'], self.envelope['transactionRevision'])
            self.assertEqual(saved['expectedResultEditorGenerationId'], 'generation-owned')
            self.assertEqual(saved['rootUndoFrameRef'], ref)
            await send({'type': 'http.response.start', 'status': 409, 'headers': []})
            await send({'type': 'http.response.body', 'body': b'{"error":"test-response"}'})
        self.boundary.app = application
        status, _, _ = asyncio.run(self.call(BASE + '/transactions/tx-owned/undo/prepare', method='POST',
                                             headers=[(b'x-inspectorpro-recovery-request', b'undo-new')]))
        self.assertEqual(status, 409)
        self.assertNotIn('lastSuccessfulTransaction', self.boundary.registry['requests']['undo-new'])

    def test_wrong_session_and_commit_without_prepare_are_rejected(self):
        path = BASE + '/transactions/tx-owned/apply/commit'
        headers = [(b'x-inspectorpro-recovery-request', b'request-new')]
        status, body, _ = asyncio.run(self.call(path, method='POST', headers=headers, session=False))
        self.assertEqual((status, body['error']['code']), (403, 'harness_session_owner_mismatch'))
        status, body, _ = asyncio.run(self.call(path, method='POST', headers=headers))
        self.assertEqual((status, body['error']['code']), (409, 'harness_request_prepare_required'))
        self.assertEqual(self.app_calls, [])


if __name__ == "__main__":
    unittest.main()
