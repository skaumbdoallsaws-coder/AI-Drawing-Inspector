"""Durable request ownership and read-only facility transaction reconciliation.

This records actual transaction service replies before delivering them. It never
constructs proposals, rewrites editor frames, renews leases or executes recovery.
"""
from __future__ import annotations
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
from desktop.runtime.profile import local_path

class TransactionJournal:
    def __init__(self, profile, host, instance_id):
        self.profile, self.host, self.instance_id = profile, host, instance_id
        self.layout_id, self.owner = profile.layout_id, profile.owner
        self.directory = local_path(profile.data / 'desktop-transactions')
        self.directory.mkdir(exist_ok=True)

    def binding(self):
        principal = self.host.principal()
        return {'identity': {key: self.profile.value[key] for key in ('backendId', 'storeId')} | {'principalId': principal.principal_id},
                'document': {'tenantId': principal.tenant_id, 'siteId': 'site-local', 'documentId': self.layout_id}, 'owner': self.owner}

    def request_path(self, request_id):
        if not isinstance(request_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request_id):
            raise ValueError('A stable desktop transaction request ID is required')
        return local_path(self.directory / (hashlib.sha256(request_id.encode()).hexdigest() + '.json'))

    def read_request(self, request_id):
        path = self.request_path(request_id)
        if not path.exists(): return None
        if path.stat().st_size > 128 * 1024 * 1024: raise ValueError('Desktop transaction journal is oversized')
        record = json.loads(path.read_text())
        if record.get('requestId') != request_id: raise ValueError('Desktop journal request identity mismatch')
        return record

    def write_request(self, request_id, record):
        target = self.request_path(request_id)
        payload = json.dumps(record, separators=(',', ':'), allow_nan=False).encode()
        if len(payload) > 128 * 1024 * 1024: raise ValueError('Desktop transaction journal exceeds its size limit')
        descriptor, name = tempfile.mkstemp(prefix='journal-', suffix='.tmp', dir=self.directory)
        try:
            with os.fdopen(descriptor, 'wb') as stream:
                stream.write(payload); stream.flush(); os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            if os.path.exists(name): os.unlink(name)

    def prepare_dispatch(self, path, value, request_id, session_id):
        if session_id != self.owner['sessionId']:
            raise ValueError('Desktop transaction session owner mismatch')
        kind = 'undo' if '/undo/' in path else 'apply'
        binding = self.binding()
        prior = self.read_request(request_id)
        if prior and (prior.get('kind') != kind or any(prior.get(key) != binding[key] for key in ('identity', 'document', 'owner'))):
            raise ValueError('Desktop transaction request binding conflict')
        tracked = deepcopy(prior) if prior else dict(deepcopy(binding), requestId=request_id, kind=kind, endpoints={})
        fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
        previous = tracked['endpoints'].get(path)
        if previous:
            if previous['fingerprint'] != fingerprint:
                raise ValueError('Desktop transaction retry differs from the original request')
            if 'response' not in previous:
                raise ValueError('Desktop transaction outcome is unknown; durable reconciliation is required before further work')
            return tracked, deepcopy(previous['response'])
        route_transaction = re.search(r'/transactions/([A-Za-z0-9_-]+)/', path)
        transaction_id = route_transaction.group(1) if route_transaction else None
        if transaction_id and (tracked.get('transactionId') not in {None, transaction_id} or value.get('transactionId') not in {None, transaction_id}):
            raise ValueError('Desktop transaction ID changed within one request')
        if kind == 'apply' and path.endswith('/apply/prepare'):
            if tracked.get('preparePath') not in {None, path}: raise ValueError('Desktop proposal request binding changed')
            generation = value.get('expectedResultEditorGenerationId')
            if not isinstance(generation, str) or not 1 <= len(generation) <= 256:
                raise ValueError('Desktop Apply requires an explicit editor generation')
            tracked.update(preparePath=path, expectedResultEditorGenerationId=generation)
        elif kind == 'undo' and prior is None and path.endswith('/undo/prepare'):
            principal = self.host.principal()
            source = self.host.design_repository.get_transaction(principal.tenant_id, 'site-local', transaction_id)
            body = source['transaction']
            if body.get('layoutId') != self.layout_id or body.get('status') != 'active' or not body.get('installedEditorGenerationId'):
                raise ValueError('Desktop Undo does not own an active installed transaction')
            tracked.update(transactionId=transaction_id, sourceTransactionId=transaction_id,
                sourceTransactionRevision=source['transactionRevision'], rootUndoFrameRef=deepcopy(body.get('rootUndoFrameRef')),
                expectedResultEditorGenerationId=body['installedEditorGenerationId'])
        elif prior is None or not tracked.get('transactionId'):
            raise ValueError('Desktop transaction preparation must precede this phase')
        tracked['endpoints'][path] = {'fingerprint': fingerprint, 'state': 'dispatching', 'dispatchInstanceId': self.instance_id}
        self.write_request(request_id, tracked)
        return tracked, None

    def finish_dispatch(self, path, tracked, status, result):
        envelope = result.get('transaction', {})
        body = envelope.get('transaction', {})
        transaction_id = body.get('transactionId')
        if transaction_id and 200 <= status < 300:
            if (tracked.get('transactionId') not in {None, transaction_id} or body.get('layoutId') != self.layout_id
                    or body.get('installedEditorGenerationId') != tracked.get('expectedResultEditorGenerationId')):
                raise ValueError('Desktop service response changed its transaction binding')
            tracked.update(transactionId=transaction_id, lastSuccessfulTransaction=deepcopy(envelope),
                lastSuccessfulLease=deepcopy(result.get('lease')), lastSuccessfulOutcome=result.get('outcome'))
        tracked['endpoints'][path].update(state='response-recorded', response={'status': status, 'body': result})
        self.write_request(tracked['requestId'], tracked)

    def lookup(self, value):
        diagnostics = {"instanceId": self.instance_id, "processId": os.getpid(), "readOnly": True, "registryReloaded": True, "transactionReads": 0, "leaseInspections": 0, "artifactReads": 0, "applicationDispatches": 0}
        binding = self.binding()
        key = value.get('requestId', '')
        tracked = self.read_request(key)
        result = dict(binding, requestId=key, transactionId=value.get('transactionId'), kind=value.get('kind'), status='unknown', lookupDiagnostics=diagnostics, writeAuthority=False, retainRecoveryHandle=True, recoveryRequired=True)
        if not tracked or any(value.get(k) != binding[k] or tracked.get(k) != binding[k] for k in ('identity', 'document', 'owner')):
            return result
        if tracked.get('kind') != value.get('kind'):
            return result
        transaction_id = tracked.get('transactionId')
        if not transaction_id or (value.get('transactionId') and transaction_id != value['transactionId']):
            return result
        retained = tracked.get('lastSuccessfulTransaction')
        generation = tracked.get('expectedResultEditorGenerationId')
        if not isinstance(retained, dict) or not isinstance(generation, str) or not generation:
            return result
        principal = self.host.principal()
        envelope = self.host.design_repository.get_transaction(principal.tenant_id, 'site-local', transaction_id)
        if diagnostics is not None:
            diagnostics['transactionReads'] += 1
        body = envelope['transaction']
        if (body.get('layoutId') != self.layout_id or body.get('transactionId') != transaction_id
                or envelope != retained or body.get('installedEditorGenerationId') != generation):
            return result
        ownership = self.host.design_loop_service.lease_repository.inspect(principal.tenant_id, 'site-local', self.layout_id)
        if diagnostics is not None:
            diagnostics['leaseInspections'] += 1
        lease = ownership.get('lease')
        if diagnostics is not None and isinstance(lease, dict):
            result.update(transactionId=transaction_id, transactionRevision=envelope['transactionRevision'], transaction=envelope, lease=lease)
            retained_lease = tracked.get('lastSuccessfulLease')
            owner_fields = ('ownerKind', 'ownerRunId', 'ownerToken')
            if not isinstance(retained_lease, dict) or any(lease.get(key) != retained_lease.get(key) for key in owner_fields):
                result.update(status='ownership_conflict', reason='Another writer owns the draft lease; explicit recovery is required')
                return result
            # Released is a valid acknowledged Undo outcome, not an expired
            # active lease, even though repository inspect reports it inactive.
            if lease.get('status') != 'released' and ownership.get('expired') is True:
                result.update(status='lease_expired', reason='The retained lease expired; explicit recovery is required')
                return result
        if (not isinstance(lease, dict) or lease != tracked.get('lastSuccessfulLease')
                or lease.get('leaseRevision') != body.get('leaseRevision')):
            return result
        owns = (lease.get('ownerKind') == 'design_run' and lease.get('ownerRunId') == body.get('designRunId')
                and lease.get('ownerToken') == body.get('leaseOwnerToken'))
        result.update(transactionId=transaction_id, transactionRevision=envelope['transactionRevision'], transaction=envelope, lease=lease)
        frame = value.get('record', {}).get('payload', {}).get('snapshot', {}).get('editorFrame')
        if not isinstance(frame, dict):
            return result
        from ai_inspector.facility_layout.design_service import facility_design_installation_fingerprint
        if (body['status'] == 'active' and tracked['kind'] == 'apply' and owns
                and ownership.get('active') is True and lease.get('status') == 'active'
                and lease.get('currentDraftRevision') == body.get('proposalBinding', {}).get('resultLayoutRevision')):
            active = frame.get('activeProposal') or {}
            if active.get('transactionId') != transaction_id or frame.get('editorGenerationId') != generation:
                return result
            fingerprint = facility_design_installation_fingerprint(draft_revision=frame['draftRevision'], proposal_id=active.get('proposalId'), proposal_revision=active.get('proposalRevision'), transaction_binding_revision=active.get('transactionBindingRevision'), editor_generation_id=frame['editorGenerationId'], command_journal_hash=frame['commandJournalHash'])
            if fingerprint == body.get('expectedInstallationFingerprint'):
                result.update(status='resolved', outcome='applied', recoveryRequired=False)
        elif body['status'] == 'undone' and tracked['kind'] == 'undo':
            released = owns and lease.get('status') == 'released' and ownership.get('active') is False
            returned = (tracked.get('lastSuccessfulOutcome') == 'returned_to_prior_owner'
                        and lease.get('status') == 'active' and ownership.get('active') is True and not owns)
            if not (released or returned) or tracked.get('sourceTransactionId') != transaction_id:
                return result
            ref = body['rootUndoFrameRef']
            if ref != tracked.get('rootUndoFrameRef'):
                return result
            root_frame = self.host.design_repository.get_artifact(principal.tenant_id, 'site-local', ref['artifactKind'], ref['artifactId'], ref['artifactRevision'])['artifact']
            if diagnostics is not None:
                diagnostics['artifactReads'] += 1
            if all(frame.get(key) == root_frame.get(key) for key in ('baseRevision', 'draftRevision', 'draftLayout', 'batches', 'cursor', 'selectedIds', 'editorGenerationId', 'commandJournalHash')):
                result.update(status='resolved', outcome='undone', recoveryRequired=False)
        return result

