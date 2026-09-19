"""Explicit isolated facility recovery harness; never used by normal shell startup.

Runs the actual application, operation kernel, design transaction service and
lease repositories. Only proposal generation is a deterministic test fixture.
Every application request requires a per-run credential; Save/provider/native
routes are denied regardless of the credential. No live roots are opened for write.
"""
from __future__ import annotations

import sys

# Flush before the wrapper's bulk imports. Module imports by tests stay silent;
# --serve alone cannot opt in unless this file is the executed entry point.
_STARTUP_DIAGNOSTICS_ENABLED = __name__ == '__main__' and '--serve' in sys.argv
if _STARTUP_DIAGNOSTICS_ENABLED:
    try:
        sys.stderr.write('INSPECTORPRO_DESKTOP_BACKEND_BOOTSTRAP_ENTERED\n')
        sys.stderr.flush()
    except (OSError, ValueError):
        pass

import time
_WRAPPER_STARTED = time.monotonic()

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import uuid

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('recovery_rendering_backend', Path(__file__).with_name('run-rendering-backend.py'))
base = importlib.util.module_from_spec(spec)
spec.loader.exec_module(base)
if _STARTUP_DIAGNOSTICS_ENABLED:
    base.enable_startup_checkpoints(started_at=_WRAPPER_STARTED)
base.startup_checkpoint('facility-wrapper-imports-completed')
CONFIG = {}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream, separators=(',', ':'))
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def permitted(method, path, layout_id):
    if '\\' in path or any(part in {'.', '..'} for part in path.split('/')):
        return False
    if method in {'GET', 'HEAD'}:
        return base.allowed_request(method, path) or path == '/api/facility-layouts/site-local/' + layout_id
    if method != 'POST':
        return False
    if path == '/api/facility-layouts/site-local/' + layout_id + '/preview':
        return True
    prefix = '/api/facility-layout-design/site-local/' + layout_id
    return bool(re.fullmatch(re.escape(prefix) + r'/(?:proposals/[A-Za-z0-9_-]+/apply/prepare|transactions/[A-Za-z0-9_-]+/(?:apply/(?:commit|acknowledge|recover)|undo/(?:prepare|acknowledge)))', path))


class RecoveryBoundary:
    def __init__(self, app, identity, instance_id=''):
        base.startup_checkpoint('recovery-boundary-entered')
        base.startup_checkpoint('recovery-boundary-imports-starting')
        import server
        from starlette.routing import Mount
        from starlette.staticfiles import StaticFiles
        from ai_inspector.facility_layout.host import build_private_local_asset_catalog, LOCAL_ASSET_CATALOG
        base.startup_checkpoint('recovery-boundary-imports-completed')
        self.app, self.identity, self.instance_id = app, identity, instance_id
        self.host = server._FACILITY_LAYOUT_HOST
        self.data = CONFIG['data_root']
        self.layout_id = CONFIG['layout_id']
        self.token = CONFIG['token']
        self.owner = CONFIG['owner']
        self.registry_path = self.data / 'recovery-harness-requests.json'
        base.startup_checkpoint('recovery-registry-read-starting')
        self.registry = json.loads(self.registry_path.read_text()) if self.registry_path.exists() else {'requests': {}, 'calls': {}, 'deniedSaveCalls': 0}
        base.startup_checkpoint('recovery-registry-read-completed')
        base.startup_checkpoint('recovery-managed-initialization-starting')
        self.initialize_managed_restart()
        base.startup_checkpoint('recovery-managed-initialization-completed')
        if getattr(self, 'managed_restart', False):
            diagnostic_spec = importlib.util.spec_from_file_location(
                'managed_facility_spatial_diagnostics', Path(__file__).with_name('facility_spatial_diagnostics.py'))
            diagnostics = importlib.util.module_from_spec(diagnostic_spec)
            diagnostic_spec.loader.exec_module(diagnostics)
            diagnostics.install_spatial_diagnostics(self.host.service.spatial_executor)
        asset_root = self.data / 'asset-project'
        if os.name == 'nt' and not str(asset_root).startswith('\\\\?\\'):
            asset_root = Path('\\\\?\\' + str(asset_root))
        base.startup_checkpoint('recovery-catalog-build-starting')
        catalog = build_private_local_asset_catalog(asset_root)
        base.startup_checkpoint('recovery-catalog-build-completed')
        base.startup_checkpoint('recovery-catalog-install-starting')
        self.host._catalog = {item['assetId']: deepcopy(item) for item in catalog}
        self.host._asset_versions = {(item['assetId'], item['assetDefinitionRevision']): deepcopy(item) for item in (*LOCAL_ASSET_CATALOG, *catalog)}
        base.startup_checkpoint('recovery-catalog-install-completed')
        # Prepend the explicitly copied asset root; generic snapshot assets remain fallback.
        base.startup_checkpoint('recovery-asset-mount-starting')
        app.router.routes.insert(0, Mount('/generated/industrial_assets', StaticFiles(directory=str(asset_root / 'generated/industrial_assets')), name='recovery-fixture-assets'))
        base.startup_checkpoint('recovery-asset-mount-completed')
        base.startup_checkpoint('recovery-boundary-completed')

    def binding(self):
        principal = self.host.principal()
        return {'identity': {key: self.identity[key] for key in ('backendId', 'storeId')} | {'principalId': principal.principal_id},
                'document': {'tenantId': principal.tenant_id, 'siteId': 'site-local', 'documentId': self.layout_id}, 'owner': self.owner}

    def initialize_managed_restart(self):
        """Only the explicitly launched managed-restart fixture gets fault controls."""
        self.managed_restart = os.environ.get('INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS') == '1'
        self.managed_lookups = []
        if self.managed_restart:
            self.clock_path = self.data / 'managed-restart-lease-clock.json'
            # All facility services share this real repository. A persisted clock
            # floor advances lease time without rewriting a lease or renewing it.
            self.host.design_loop_service.lease_repository._clock = self.managed_clock

    def managed_clock(self):
        now = datetime.now(timezone.utc)
        if self.clock_path.exists():
            value = json.loads(self.clock_path.read_text())
            floor = datetime.fromisoformat(value['notBefore'].replace('Z', '+00:00'))
            if floor.tzinfo is None:
                raise ValueError('Managed recovery clock must include its timezone')
            now = max(now, floor.astimezone(timezone.utc))
        return now

    def runtime(self):
        if not getattr(self, 'managed_restart', False):
            raise ValueError('Explicit managed-restart harness required')
        return self.binding() | {'instanceId': self.instance_id, 'origin': self.identity['origin'],
                                 'processId': os.getpid(), 'mode': 'facility-managed-backend-recovery-test'}

    def reload_registry(self):
        # A restarted process must consult durable request bindings, rather than
        # rebuilding authority from the renderer's recovery handle.
        self.registry = json.loads(self.registry_path.read_text()) if self.registry_path.exists() else {'requests': {}, 'calls': {}, 'deniedSaveCalls': 0}

    def lease_fault(self, value):
        if not getattr(self, 'managed_restart', False):
            raise ValueError('Explicit managed-restart harness required')
        if set(value) != {'identity', 'document', 'owner', 'requestId', 'transactionId', 'fault'} or value['fault'] not in {'expire', 'takeover'}:
            raise ValueError('Managed lease fault requires a complete explicit transaction binding')
        self.reload_registry()
        binding = self.binding()
        tracked = self.registry['requests'].get(value['requestId'])
        if (not tracked or tracked.get('transactionId') != value['transactionId']
                or any(value.get(key) != binding[key] or tracked.get(key) != binding[key] for key in ('identity', 'document', 'owner'))):
            raise ValueError('Managed lease fault does not own this tracked transaction')
        principal = self.host.principal()
        transaction = self.host.design_repository.get_transaction(principal.tenant_id, 'site-local', value['transactionId'])
        body = transaction['transaction']
        repository = self.host.design_loop_service.lease_repository
        ownership = repository.inspect(principal.tenant_id, 'site-local', self.layout_id)
        lease = ownership.get('lease')
        if (body.get('layoutId') != self.layout_id or transaction != tracked.get('lastSuccessfulTransaction')
                or not isinstance(lease, dict) or lease != tracked.get('lastSuccessfulLease')
                or lease.get('leaseRevision') != body.get('leaseRevision')
                or lease.get('ownerKind') != 'design_run' or lease.get('ownerRunId') != body.get('designRunId')
                or lease.get('ownerToken') != body.get('leaseOwnerToken')
                or lease.get('status') not in {'active', 'adopting', 'review_required'} or not ownership.get('active')):
            raise ValueError('Managed lease fault requires this transaction\'s current live lease')
        deadlines = [datetime.fromisoformat(lease['expiresAt'].replace('Z', '+00:00'))]
        if lease.get('recoveryDeadlineAt'):
            deadlines.append(datetime.fromisoformat(lease['recoveryDeadlineAt'].replace('Z', '+00:00')))
        clock_now = max(self.managed_clock(), *deadlines) + timedelta(seconds=1)
        write_json(self.clock_path, {'notBefore': clock_now.isoformat(), 'fault': value['fault'],
                                     'requestId': value['requestId'], 'transactionId': value['transactionId']})
        expired = repository.inspect(principal.tenant_id, 'site-local', self.layout_id)
        if expired.get('active') or not expired.get('expired'):
            raise RuntimeError('Managed lease clock did not expire the original lease')
        if value['fault'] == 'takeover':
            repository.acquire(tenant_id=principal.tenant_id, site_id='site-local', layout_id=self.layout_id,
                owner_kind='manual_write', owner_run_id='managed-other-writer-' + uuid.uuid4().hex,
                base_saved_layout_revision=lease['baseSavedLayoutRevision'], current_draft_revision=lease['currentDraftRevision'])
        after = repository.inspect(principal.tenant_id, 'site-local', self.layout_id)
        return {'fault': value['fault'], 'instanceId': self.instance_id, 'transactionId': value['transactionId'],
                'clockNow': clock_now.isoformat(), 'lease': after['lease'], 'ownership': after,
                'writeAuthority': False, 'recoveryRequired': True}

    def proposal(self, value):
        """Seed a bounded operation-kernel candidate; transaction machinery is real."""
        from ai_inspector.facility_layout.design_brief import design_revision
        host, principal = self.host, self.host.principal()
        saved = host.service.get_layout(principal, 'site-local', self.layout_id)
        operations = value.get('operations')
        if not isinstance(operations, list) or not 1 <= len(operations) <= 3:
            raise ValueError('Fixture proposal requires one to three explicit operations')
        prior_operations = []
        if value.get('editorFrame'):
            from ai_inspector.facility_layout.design_service import validate_facility_design_editor_frame
            restored_frame = host._authoritative_design_editor_frame(value['editorFrame'], current=saved,
                tenant_id=principal.tenant_id, site_id='site-local', layout_id=self.layout_id)
            frame = validate_facility_design_editor_frame(restored_frame)
            if frame['baseRevision'] != saved['revision'] or frame['baseLayout'] != saved['layout']:
                raise ValueError('Proposal fixture editor frame belongs to a different saved base')
            prior_operations = [op for batch in frame['batches'][:frame['cursor']] for op in batch['operations']]
            replayed = host.service.preview_operations(principal, 'site-local', self.layout_id, saved['revision'], prior_operations)
            if replayed['revision'] != frame['draftRevision'] or replayed['document'] != frame['draftLayout']:
                raise ValueError('Proposal fixture editor frame journal does not reproduce its draft')
        preview = host.service.preview_operations(principal, 'site-local', self.layout_id, saved['revision'], prior_operations + operations)
        identifier = 'desktop-recovery-' + uuid.uuid4().hex
        def artifact(kind, suffix, body):
            ref = {'artifactKind': kind, 'artifactId': identifier + suffix, 'artifactRevision': design_revision(body)}
            host.design_repository.store_artifact(tenant_id=principal.tenant_id, site_id='site-local', artifact_kind=kind, artifact_id=ref['artifactId'], artifact_revision=ref['artifactRevision'], artifact=body)
            return ref
        candidate = {'candidateLayout': preview['document'], 'resultLayoutRevision': preview['revision'], 'operations': operations}
        candidate_ref = artifact('design_candidate', '-candidate', candidate)
        evaluation_ref = artifact('design_evaluation', '-evaluation', {'mode': 'explicit-recovery-test-fixture', 'plannerAcceptance': False})
        base_ref = artifact('design_base', '-base', {'document': saved['layout'], 'layoutRevision': saved['revision']})
        proposal = {'proposalId': identifier, 'runId': identifier + '-run', 'layoutId': self.layout_id,
                    'briefRevision': design_revision({'fixture': identifier}), 'baseRef': base_ref,
                    'resultLayoutRevision': preview['revision'], 'diffHash': design_revision(operations),
                    'operationPlanRevision': design_revision({'operations': operations}),
                    'candidateRef': candidate_ref, 'evaluationRef': evaluation_ref, 'stageReceiptRefs': []}
        revision = design_revision(proposal)
        host.design_repository.store_artifact(tenant_id=principal.tenant_id, site_id='site-local', artifact_kind='design_proposal', artifact_id=identifier, artifact_revision=revision, artifact=proposal)
        return {'proposalId': identifier, 'proposalRevision': revision, 'candidateLayout': preview['document'], 'resultLayoutRevision': preview['revision'], 'mode': 'deterministic-proposal-real-transaction-service'}

    def transaction(self, value):
        if not getattr(self, 'managed_restart', False):
            return self._transaction(value)
        self.reload_registry()
        diagnostics = {'instanceId': self.instance_id, 'processId': os.getpid(), 'readOnly': True,
                       'registryReloaded': True, 'transactionReads': 0, 'leaseInspections': 0, 'artifactReads': 0,
                       'applicationDispatches': 0, 'registrySha256': hashlib.sha256(self.registry_path.read_bytes()).hexdigest() if self.registry_path.exists() else None,
                       'transactionCalls': deepcopy(self.registry['calls'])}
        result = self._transaction(value, diagnostics)
        result['lookupDiagnostics'] = diagnostics
        # Resolution proves an existing outcome. It does not acquire/renew a lease
        # or authorize Save; the desktop recovery coordinator owns that gate.
        result.update(writeAuthority=False, recoveryRequired=result['status'] != 'resolved', retainRecoveryHandle=True)
        self.managed_lookups.append({'requestId': result['requestId'], 'transactionId': result.get('transactionId'),
                                     'status': result['status'], **deepcopy(diagnostics)})
        return result

    def _transaction(self, value, diagnostics=None):
        binding = self.binding()
        key = value.get('requestId', '')
        tracked = self.registry['requests'].get(key)
        result = dict(binding, requestId=key, transactionId=value.get('transactionId'), kind=value.get('kind'), status='unknown')
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
                result.update(status='resolved', outcome='applied')
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
                result.update(status='resolved', outcome='undone')
        return result

    async def __call__(self, scope, receive, send):
        from starlette.responses import JSONResponse
        if scope['type'] == 'websocket':
            return await send({'type': 'websocket.close', 'code': 1008})
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        headers = dict(scope.get('headers', []))
        origin = self.identity['origin']
        valid_origin = headers.get(b'origin') in {None, origin.encode()}
        valid_host = headers.get(b'host') == origin.removeprefix('http://').encode()
        path, method = scope['path'], scope['method']
        if valid_host and valid_origin and path == base.IDENTITY_PATH and method == 'GET':
            return await JSONResponse(base.public_identity(self.identity), headers={'X-InspectorPro-Rendering-Instance': self.instance_id, 'Cache-Control': 'no-store'})(scope, receive, send)
        if not valid_host or not valid_origin or headers.get(b'x-inspectorpro-recovery-test') != self.token.encode():
            return await JSONResponse({'error': {'code': 'isolated_recovery_harness_required'}}, status_code=403)(scope, receive, send)
        custom = path.startswith('/__facility-recovery__/')
        if not custom and not permitted(method, path, self.layout_id):
            if method in {'POST', 'PUT', 'PATCH'} and (path.endswith('/save') or path == '/api/facility-layouts/site-local/' + self.layout_id):
                self.registry['deniedSaveCalls'] += 1
                write_json(self.registry_path, self.registry)
            return await JSONResponse({'error': {'code': 'facility_recovery_operation_denied'}}, status_code=403)(scope, receive, send)
        body = b''
        if method == 'POST':
            while True:
                message = await receive()
                if message['type'] != 'http.request':
                    raise ValueError('Unexpected harness request body')
                body += message.get('body', b'')
                if len(body) > 8 * 1024 * 1024:
                    return await JSONResponse({'error': {'code': 'harness_body_limit'}}, status_code=413)(scope, receive, send)
                if not message.get('more_body'):
                    break
        value = json.loads(body or b'{}')
        if custom:
            try:
                if path == '/__facility-recovery__/page' and method == 'GET':
                    from starlette.responses import FileResponse
                    return await FileResponse(Path(__file__).with_name('facility-recovery-page.html'), media_type='text/html')(scope, receive, send)
                elif path == '/__facility-recovery__/identity' and method == 'GET':
                    result = self.binding() | {'mode': 'facility-recovery-test', 'researchBrowsing': False, 'savedLayoutId': self.layout_id}
                elif path == '/__facility-recovery__/runtime' and method == 'GET' and getattr(self, 'managed_restart', False):
                    result = self.runtime()
                elif path == '/__facility-recovery__/lease-fault' and method == 'POST' and getattr(self, 'managed_restart', False):
                    result = self.lease_fault(value)
                elif path == '/__facility-recovery__/proposal' and method == 'POST':
                    result = self.proposal(value)
                elif path == '/__facility-recovery__/transaction' and method == 'POST':
                    result = self.transaction(value)
                elif path == '/__facility-recovery__/evidence' and method == 'GET':
                    result = {'calls': self.registry['calls'], 'deniedSaveCalls': self.registry['deniedSaveCalls'], 'requests': {k: {'kind': v['kind'], 'transactionId': v.get('transactionId')} for k, v in self.registry['requests'].items()}}
                    if getattr(self, 'managed_restart', False):
                        result.update(runtime=self.runtime(), lookups=deepcopy(self.managed_lookups))
                else:
                    return await JSONResponse({'error': {'code': 'harness_route_denied'}}, status_code=403)(scope, receive, send)
                return await JSONResponse(result, headers={'Cache-Control': 'no-store'})(scope, receive, send)
            except Exception as error:
                return await JSONResponse({'error': {'code': getattr(error, 'code', 'harness_request_failed'), 'message': str(error)}}, status_code=409)(scope, receive, send)
        request_id = headers.get(b'x-inspectorpro-recovery-request', b'').decode()
        kind = 'undo' if '/undo/' in path else 'apply'
        is_transaction = method == 'POST' and '/api/facility-layout-design/' in path
        if is_transaction:
            if headers.get(b'x-inspectorpro-session') != self.owner['sessionId'].encode():
                return await JSONResponse({'error': {'code': 'harness_session_owner_mismatch'}}, status_code=403)(scope, receive, send)
            if not re.fullmatch(r'[A-Za-z0-9_-]{1,128}', request_id):
                return await JSONResponse({'error': {'code': 'harness_request_identity_required'}}, status_code=403)(scope, receive, send)
            prior = self.registry['requests'].get(request_id)
            binding = self.binding()
            if prior and (prior.get('kind') != kind or any(prior.get(key) != binding[key] for key in ('identity', 'document', 'owner'))):
                return await JSONResponse({'error': {'code': 'harness_request_identity_conflict'}}, status_code=409)(scope, receive, send)
            tracked = deepcopy(prior) if prior else dict(deepcopy(binding), kind=kind, responses=[], requestFingerprints={})
            fingerprint = hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()
            previous_fingerprint = tracked.setdefault('requestFingerprints', {}).get(path)
            if previous_fingerprint is not None and previous_fingerprint != fingerprint:
                return await JSONResponse({'error': {'code': 'harness_request_identity_conflict'}}, status_code=409)(scope, receive, send)
            route_transaction = re.search(r'/transactions/([A-Za-z0-9_-]+)/', path)
            transaction_id = route_transaction.group(1) if route_transaction else None
            if transaction_id and (tracked.get('transactionId') not in {None, transaction_id}
                                   or value.get('transactionId') not in {None, transaction_id}):
                return await JSONResponse({'error': {'code': 'harness_request_transaction_conflict'}}, status_code=409)(scope, receive, send)
            if kind == 'apply' and path.endswith('/apply/prepare'):
                if tracked.get('preparePath') not in {None, path}:
                    return await JSONResponse({'error': {'code': 'harness_request_identity_conflict'}}, status_code=409)(scope, receive, send)
                tracked['preparePath'] = path
                generation = value.get('expectedResultEditorGenerationId')
                if not isinstance(generation, str) or not 1 <= len(generation) <= 256:
                    return await JSONResponse({'error': {'code': 'harness_request_generation_required'}}, status_code=409)(scope, receive, send)
                if tracked.get('expectedResultEditorGenerationId') not in {None, generation}:
                    return await JSONResponse({'error': {'code': 'harness_request_generation_conflict'}}, status_code=409)(scope, receive, send)
                tracked['expectedResultEditorGenerationId'] = generation
            elif kind == 'undo' and prior is None and path.endswith('/undo/prepare'):
                principal = self.host.principal()
                source = self.host.design_repository.get_transaction(principal.tenant_id, 'site-local', transaction_id)
                source_body = source['transaction']
                if (source_body.get('layoutId') != self.layout_id or source_body.get('transactionId') != transaction_id
                        or source_body.get('status') != 'active' or not source_body.get('installedEditorGenerationId')):
                    return await JSONResponse({'error': {'code': 'harness_request_source_conflict'}}, status_code=409)(scope, receive, send)
                tracked.update(transactionId=transaction_id, sourceTransactionId=transaction_id,
                    sourceTransactionRevision=source['transactionRevision'], rootUndoFrameRef=deepcopy(source_body.get('rootUndoFrameRef')),
                    expectedResultEditorGenerationId=source_body['installedEditorGenerationId'])
            elif prior is None or not tracked.get('transactionId'):
                return await JSONResponse({'error': {'code': 'harness_request_prepare_required'}}, status_code=409)(scope, receive, send)
            tracked['requestFingerprints'][path] = fingerprint
            self.registry['requests'][request_id] = tracked
            # Retain ownership before dispatch; an interrupted response cannot invent a binding later.
            write_json(self.registry_path, self.registry)
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type': 'http.request', 'body': body, 'more_body': False}
            return await receive()
        messages = []
        if not is_transaction:
            return await self.app(scope, replay if method == 'POST' else receive, send)
        async def capture(message):
            messages.append(message)
        await self.app(scope, replay, capture)
        response_body = b''.join(m.get('body', b'') for m in messages if m['type'] == 'http.response.body')
        result = json.loads(response_body or b'{}')
        tracked = self.registry['requests'][request_id]
        envelope = result.get('transaction', {})
        transaction_body = envelope.get('transaction', {})
        transaction_id = transaction_body.get('transactionId')
        response_status = next(m['status'] for m in messages if m['type'] == 'http.response.start')
        if transaction_id and 200 <= response_status < 300:
            if (tracked.get('transactionId') not in {None, transaction_id}
                    or transaction_body.get('layoutId') != self.layout_id
                    or transaction_body.get('installedEditorGenerationId') != tracked.get('expectedResultEditorGenerationId')):
                raise RuntimeError('A request response changed its transaction/document/editor-generation binding')
            tracked['transactionId'] = transaction_id
            tracked['lastSuccessfulTransaction'] = deepcopy(envelope)
            tracked['lastSuccessfulLease'] = deepcopy(result.get('lease'))
            tracked['lastSuccessfulOutcome'] = result.get('outcome')
        self.registry['calls'][path] = self.registry['calls'].get(path, 0) + 1
        tracked['responses'].append({'path': path, 'status': response_status, 'transactionRevision': envelope.get('transactionRevision')})
        write_json(self.registry_path, self.registry)
        for message in messages:
            await send(message)


def main():
    base.startup_checkpoint('facility-main-entered')
    base.startup_checkpoint('facility-arguments-parsing')
    parser = argparse.ArgumentParser()
    parser.add_argument('--serve', action='store_true', required=True)
    parser.add_argument('--data-root', type=Path, required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--profile-id', required=True)
    parser.add_argument('--token-file', type=Path, required=True)
    args = parser.parse_args()
    base.startup_checkpoint('facility-arguments-parsed')
    base.startup_checkpoint('facility-harness-validation-starting')
    if os.environ.get('INSPECTORPRO_FACILITY_RECOVERY_HARNESS') != '1':
        raise ValueError('Explicit isolated recovery harness environment required')
    data = base.no_links(args.data_root)
    token_path = base.no_links(args.token_file)
    if not base.within(token_path, data):
        raise ValueError('Harness credential must be inside its isolated root')
    token = token_path.read_text().strip()
    if not re.fullmatch(r'[a-f0-9]{64}', token):
        raise ValueError('Invalid isolated harness credential')
    base.startup_checkpoint('facility-harness-validation-completed')
    base.startup_checkpoint('facility-manifest-read-starting')
    manifest = json.loads((data / 'facility-recovery-fixture.json').read_text())
    base.startup_checkpoint('facility-manifest-read-completed')
    base.startup_checkpoint('facility-fixture-validation-starting')
    library, identity = base.prepare_fixture(ROOT, data, args.profile_id, args.port)
    base.startup_checkpoint('facility-fixture-validation-completed')
    base.startup_checkpoint('facility-owner-initialization-starting')
    owner_path = data / 'facility-recovery-owner.json'
    if not owner_path.exists():
        write_json(owner_path, {'sessionId': 'desktop-recovery-' + uuid.uuid4().hex, 'ownerId': 'isolated-recovery-' + uuid.uuid4().hex})
    CONFIG.update(data_root=data, layout_id=manifest['layout']['layoutId'], token=token, owner=json.loads(owner_path.read_text()))
    base.startup_checkpoint('facility-owner-initialization-completed')
    args.data_root = data
    base.RenderingBoundary = RecoveryBoundary
    base.startup_checkpoint('facility-serve-dispatching')
    base.serve(args, library, identity)


if __name__ == '__main__':
    main()
