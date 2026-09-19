"""Offline proposal preparation for explicitly isolated full-app acceptance.

Uses the already accepted proposal fixture and actual operation/design services.
It adds no HTTP route, runs no model/provider/compiler, and never saves a layout.
"""
from __future__ import annotations
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
import argparse
from copy import deepcopy
import hashlib
import importlib.util
import json
import os
from types import SimpleNamespace
import uuid

from desktop.runtime.profile import load_profile, local_path, read_json, write_exclusive
from desktop.runtime.managed_backend import configure_environment, install_runtime_guard


def accepted_proposal_fixture():
    spec = importlib.util.spec_from_file_location('offline_runtime_proposal_fixture', Path(__file__).with_name('facility-recovery-backend.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.RecoveryBoundary.proposal


def seed_proposal(profile, host):
    from ai_inspector.facility_layout.design_brief import design_revision
    from ai_inspector.facility_layout.design_service import FACILITY_DESIGN_EDITOR_FRAME_VERSION
    if profile.layout_id is None:
        raise ValueError('An explicit marked isolated facility acceptance profile is required')
    target = local_path(profile.data / 'runtime-proposal.json')
    if target.exists(): raise ValueError('Offline runtime proposal already exists; use a fresh acceptance profile')
    manifest = read_json(profile.data / 'facility-recovery-fixture.json', 4 * 1024 * 1024)
    saved_path = local_path(profile.data / manifest['layout']['relativePath'])
    if profile.data not in saved_path.parents: raise ValueError('Isolated saved layout escaped its selected store')
    before = hashlib.sha256(saved_path.read_bytes()).hexdigest()
    if before != manifest['layout']['revision']: raise ValueError('Isolated saved layout provenance changed')
    principal = host.principal()
    saved = host.service.get_layout(principal, 'site-local', profile.layout_id)
    zones = saved['layout'].get('zones', [])
    if not zones or not zones[0].get('zoneId'): raise ValueError('Acceptance layout requires its actual first zone')
    zone = zones[0]
    prefix = (zone.get('label') or 'Facility zone')[:65]
    labels = {'original': zone.get('label', ''), 'edit1': prefix + ' [desktop edit 1]',
              'edit2': prefix + ' [desktop edit 2]', 'apply': prefix + ' [desktop Apply]'}
    def edit(label): return {'op': 'edit_zone', 'zoneId': zone['zoneId'], 'patch': {'label': label}}
    prior = [edit(labels['edit1']), edit(labels['edit2'])]
    manual = host.service.preview_operations(principal, 'site-local', profile.layout_id, saved['revision'], prior)
    batches = [{'label': 'Offline acceptance manual edit ' + str(index + 1), 'operations': [operation]}
               for index, operation in enumerate(prior)]
    frame = {'schemaVersion': FACILITY_DESIGN_EDITOR_FRAME_VERSION, 'baseLayout': saved['layout'], 'baseRevision': saved['revision'],
             'draftLayout': manual['document'], 'draftRevision': manual['revision'], 'batches': batches, 'cursor': 2,
             'selectedIds': [zone['zoneId']], 'generatedDraft': None, 'recentReceiptIds': [], 'activeProposal': None,
             'editorGenerationId': 'offline-proposal-' + uuid.uuid4().hex,
             'commandJournalHash': design_revision({'baseRevision': saved['revision'], 'batches': batches, 'cursor': 2, 'generatedDraft': None})}
    # This helper invokes the existing fixture's method directly, without its
    # ASGI boundary, test endpoints, request registry, or backend initialization.
    reference = accepted_proposal_fixture()(SimpleNamespace(host=host, layout_id=profile.layout_id),
                                           {'operations': [edit(labels['apply'])], 'editorFrame': frame})
    after = hashlib.sha256(saved_path.read_bytes()).hexdigest()
    if before != after: raise RuntimeError('Offline proposal generation changed saved layout bytes')
    result = {'schemaVersion': 1, 'mode': 'offline-runtime-acceptance-proposal',
              'identity': {key: profile.value[key] for key in ('backendId', 'storeId', 'profileId')} | {'storeBinding': profile.marker['storeBinding']},
              'layoutId': profile.layout_id, 'zoneId': zone['zoneId'], 'labels': labels,
              'savedRevision': saved['revision'], 'manualDraftRevision': manual['revision'], 'resultLayoutRevision': reference['resultLayoutRevision'],
              'proposal': {key: reference[key] for key in ('proposalId', 'proposalRevision')},
              'savedLayoutSha256Before': before, 'savedLayoutSha256After': after,
              'providerCalls': 0, 'saveCalls': 0, 'plannerAcceptance': False}
    write_exclusive(target, result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-file', type=Path, required=True)
    args = parser.parse_args()
    profile = load_profile(args.profile_file, ROOT)
    if profile.layout_id is None: raise ValueError('Offline seeding requires an explicit isolated acceptance document')
    if (profile.data / 'runtime-proposal.json').exists(): raise ValueError('Offline proposal already exists')
    configure_environment(profile)
    install_runtime_guard(profile.data)
    from ai_inspector.facility_layout.host import LocalFacilityLayoutHost
    from ai_inspector.facility_layout.feature_flags import FacilityLayoutFeatureFlags
    asset_root = local_path(profile.data / 'asset-project')
    if os.name == 'nt': asset_root = Path('\\\\?\\' + str(asset_root))
    host = LocalFacilityLayoutHost(profile.data / 'facility', private_assets=True, private_asset_root=asset_root,
                                  feature_flags=FacilityLayoutFeatureFlags.from_environment())
    try: result = seed_proposal(profile, host)
    finally: host.close()
    print(json.dumps({'path': str(profile.data / 'runtime-proposal.json'), 'proposal': result['proposal'],
                      'savedLayoutUnchanged': result['savedLayoutSha256Before'] == result['savedLayoutSha256After']}))


if __name__ == '__main__':
    try: main()
    except Exception as error:
        print(str(error), file=sys.stderr); raise SystemExit(1)
