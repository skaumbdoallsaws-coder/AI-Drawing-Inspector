"""Opt-in normal-profile activation/rollback; never install source or move stores.

Dry-run by default, with no vault or key-file access. Each --acceptance takes
REPORT REPORT_SHA256 EVIDENCE_SHA256, where REPORT is the final native
codex-desktop-acceptance.json, not an intermediate UI report. Supply every gate
approved by the reviewer. Edit enablement additionally requires an editing pass.

Apply requires --desktop-stopped AND a successful process/listener check. Keep
the desktop closed throughout the transaction; the check is not a process lock.
--provision-credential requires --api-key-file; replacing an existing credential
also requires --replace-credential. Rollback never accesses/deletes credentials.
Interrupted transactions retain their original bytes and a hash-pinned record.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import ctypes
import hashlib
import json
import os
from pathlib import Path
import re
import socket
import sys
from urllib.parse import urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime import codex_credentials as credentials
from desktop.runtime.application_profile import load_application_profile
from desktop.runtime.codex_config import MODEL, validate_config, validate_package
from desktop.runtime.profile import canonical, local_path, read_json
from tools import codex_desktop_pack as pack
from tools.check_codex_sage_desktop import application_code_files

RECORD = 'codex-profile-activation.json'


class Refused(ValueError):
    """Only constant, non-sensitive codes may be passed to this exception."""


def require(condition, code):
    if not condition:
        raise Refused(code)


def sha_bytes(value):
    return hashlib.sha256(value).hexdigest()


def check_hash(file, expected):
    require(isinstance(expected, str) and re.fullmatch(r'[a-f0-9]{64}', expected), 'approval_hash_required')
    require(pack.digest(local_path(file)) == expected, 'approved_file_changed')


def json_object(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    result = json.loads(data.decode('utf-8'), object_pairs_hook=unique)
    require(isinstance(result, dict), 'json_object_required')
    canonical(result)  # Reject non-finite numbers before any transaction.
    return result


def normal_root(path):
    root = local_path(path)
    require(root == local_path(ROOT), 'activation_tool_must_run_from_selected_checkout')
    return root


def verify_acceptances(items, app_root, release, package_hash, edit_previews):
    require(bool(items), 'accepted_native_evidence_required')
    current = application_code_files(app_root)
    current_hash = sha_bytes(canonical(current))
    approved, scenarios, seen = [], set(), set()
    for report_path, report_hash, evidence_hash in items:
        report_path = local_path(report_path)
        require(report_path.name == 'codex-desktop-acceptance.json' and report_path not in seen,
                'final_unique_acceptance_report_required')
        seen.add(report_path)
        check_hash(report_path, report_hash)
        report = read_json(report_path, 64 * 1024 * 1024)
        require(report.get('status') == 'passed', 'native_acceptance_not_passed')
        evidence_path = local_path(report_path.parent / 'application-code-evidence.json')
        require(local_path(report.get('applicationCodeEvidence', '')) == evidence_path,
                'native_evidence_binding_invalid')
        check_hash(evidence_path, evidence_hash)
        evidence = read_json(evidence_path, 64 * 1024 * 1024)
        require(type(evidence.get('schemaVersion')) is int and evidence['schemaVersion'] == 1
                and evidence.get('status') == 'verified'
                and evidence.get('applicationCodeUnchanged') is True
                and evidence.get('dependencyBundleUnchanged') is True
                and local_path(evidence.get('appRoot', '')) == app_root
                and local_path(evidence.get('releaseRoot', '')) == release
                and evidence.get('packageSha256') == package_hash
                and evidence.get('before') == current and evidence.get('after') == current
                and evidence.get('beforeSha256') == current_hash
                and evidence.get('afterSha256') == current_hash,
                'native_evidence_or_application_code_changed')
        scenario = report.get('scenario') or ('memory' if report.get('memoryCheck') else
                   'cancel' if report.get('cancelOnly') else 'readonly')
        require(scenario in {'startup', 'recovery', 'editing', 'editor-change', 'memory', 'cancel', 'readonly'},
                'native_scenario_invalid')
        scenarios.add(scenario)
        approved.append({'reportFile': str(report_path), 'reportSha256': report_hash,
                         'evidenceSha256': evidence_hash, 'scenario': scenario})
        check_hash(report_path, report_hash)
        check_hash(evidence_path, evidence_hash)
    require(not edit_previews or 'editing' in scenarios, 'accepted_editing_evidence_required')
    return approved, current_hash


def process_snapshot():
    """Fail closed if a potentially relevant process cannot be inspected."""
    import psutil
    result = []
    for process in psutil.process_iter(['pid', 'name']):
        if process.pid == os.getpid():
            continue
        name = (process.info.get('name') or '').lower()
        # The pinned runtime is codex.exe, not the unrelated authoring app's
        # protected codex-windows-sandbox-service or code-mode helpers.
        if not (any(word in name for word in ('python', 'electron', 'inspectorpro', 'node'))
                or name in {'codex', 'codex.exe'}):
            continue
        try:
            with process.oneshot():
                result.append({'cmdline': process.cmdline(), 'cwd': process.cwd(), 'exe': process.exe()})
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            raise Refused('desktop_process_state_unavailable') from None
    return result


def listener_open(origin):
    url = urlsplit(origin)
    try:
        # Windows can take about two seconds to return WSAECONNREFUSED even
        # for an unused loopback port. A timeout must remain an unknown state.
        with socket.create_connection((url.hostname, url.port), timeout=5):
            return True
    except ConnectionRefusedError:
        return False
    except OSError:
        raise Refused('desktop_listener_state_unavailable') from None


def assert_stopped(profile, profile_file, app_root, release, *, stopped,
                   processes=None, listener=None):
    require(stopped is True, 'explicit_desktop_stopped_precondition_required')
    rows = (processes or process_snapshot)()
    roots = [str(app_root), str(release), str(profile_file),
             str(local_path(profile['dataRoot']) / 'codex-pilot')]
    roots = [value.replace('\\', '/').casefold() for value in roots]
    for row in rows:
        require(isinstance(row.get('cmdline'), list) and row.get('cwd') and row.get('exe'),
                'desktop_process_state_unavailable')
        text = '\n'.join([*row['cmdline'], row['cwd'], row['exe']]).replace('\\', '/').casefold()
        # Unrelated Codex authoring sessions may use the same cwd. Only the
        # selected dependency bundle/pilot state binds a Codex process to us.
        selected = [roots[1], roots[3]] if 'codex' in Path(row['exe']).name.lower() else roots
        require(not any(root in text for root in selected), 'desktop_or_backend_still_running')
    require(not (listener or listener_open)(profile['origin']), 'desktop_origin_still_listening')


def credential_exists(profile_id):
    target = credentials.credential_target(profile_id)
    vault = credentials._vault()
    pointer = ctypes.POINTER(credentials.Credential)()
    if not vault.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        require(ctypes.get_last_error() == 1168, 'credential_presence_unavailable')
        return False
    try:
        return True
    finally:
        if pointer and pointer.contents.CredentialBlob and pointer.contents.CredentialBlobSize:
            ctypes.memset(pointer.contents.CredentialBlob, 0, pointer.contents.CredentialBlobSize)
        vault.CredFree(pointer)


def read_key_file(file):
    from dotenv import dotenv_values
    values = dotenv_values(local_path(file), interpolate=False)
    try:
        return credentials.validate_key(values.get('INSPECTORPRO_CODEX_API_KEY') or values.get('OPENAI_API_KEY'))
    finally:
        values.clear()


def ensure_credential(profile_id, *, provision=False, replace=False, key_file=None):
    require(not replace or provision, 'credential_replace_requires_provision')
    require(provision == (key_file is not None), 'explicit_key_file_and_provision_required')
    exists = credential_exists(profile_id)
    if not provision:
        require(exists, 'existing_credential_or_explicit_provision_required')
        key = credentials.read_api_key(profile_id)
        try:
            credentials.validate_key(key)
        finally:
            del key
        return 'reused'
    require(not exists or replace, 'existing_credential_replacement_not_authorized')
    key = read_key_file(key_file)
    try:
        # WinCred has no create-if-absent operation. Recheck immediately before
        # writing; the caller must exclude other credential provisioning tools.
        require(replace or not credential_exists(profile_id), 'credential_appeared_before_provision')
        credentials.store_api_key(profile_id, key)
    finally:
        del key
    return 'replaced' if exists else 'provisioned'


@contextmanager
def profile_lock(profile_file):
    file = local_path(profile_file.with_name(profile_file.name + '.codex-activation.lock'))
    token = uuid.uuid4().hex.encode('ascii')
    with file.open('xb') as stream:
        stream.write(token)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        yield
    finally:
        # Never delete a lock changed by somebody else. A killed process leaves
        # its lock for explicit operator review alongside the rollback record.
        if file.read_bytes() == token:
            file.unlink()


def plan_activation(*, app_root, release, profile_file, backup, package_sha256,
                    profile_sha256, acceptances, edit_previews=False):
    app_root = normal_root(app_root)
    release, profile_file, backup = map(local_path, (release, profile_file, backup))
    require(profile_file.suffix.lower() == '.json' and not profile_file.name.lower().startswith('.env'),
            'application_profile_json_required')
    require(not backup.exists(), 'fresh_rollback_directory_required')
    pack.separate(app_root, release)
    pack.separate(app_root, backup)
    pack.separate(release, backup)
    require(not pack.within(app_root, backup) and not pack.within(profile_file, backup), 'rollback_path_overlap')
    bundle = pack.verify_bundle(release)
    require(bundle['packageSha256'] == package_sha256, 'approved_package_hash_mismatch')
    check_hash(profile_file, profile_sha256)
    validated = load_application_profile(profile_file).value
    original = profile_file.read_bytes()
    require(sha_bytes(original) == profile_sha256, 'profile_changed_during_read')
    raw = json_object(original)
    require('codexRuntime' not in raw, 'profile_already_has_codex_runtime')
    for name in ('dataRoot', 'facilityRoot', 'libraryRoot'):
        pack.separate(local_path(validated[name]), release)
        pack.separate(local_path(validated[name]), backup)
    approved, code_hash = verify_acceptances(acceptances, app_root, release, package_sha256, edit_previews)
    config = {'schemaVersion': 1, 'model': MODEL, 'allowPaidInference': True, 'editPreviews': edit_previews,
              'dependencyRoot': str(release / pack.DEPS),
              'binary': str(release / pack.DEPS / 'codex_cli_bin/bin/codex.exe'),
              'pilotRoot': str(local_path(validated['dataRoot']) / 'codex-pilot'),
              'credentialTarget': credentials.credential_target(raw['profileId']), 'packageSha256': package_sha256}
    validate_config(config, validated)
    validate_package(config, app_root)
    updated = canonical(dict(raw, codexRuntime=config))
    require(len(updated) <= 16384, 'enabled_profile_too_large')
    record = {'schemaVersion': 1, 'kind': 'codex-normal-profile-only', 'profileFile': str(profile_file),
              'appRoot': str(app_root), 'releaseRoot': str(release), 'packageSha256': package_sha256,
              'bundleSha256': pack.digest(release / pack.BUNDLE), 'applicationCodeSha256': code_hash,
              'profileBeforeSha256': profile_sha256, 'profileAfterSha256': sha_bytes(updated),
              'acceptances': approved}
    return record, original, updated, validated


def activate(*, apply=False, stopped=False, allow_paid=False, provision=False, replace=False,
             key_file=None, processes=None, listener=None, writer=None, **options):
    require(not replace or provision, 'credential_replace_requires_provision')
    require(provision == (key_file is not None), 'explicit_key_file_and_provision_required')
    record, original, updated, profile = plan_activation(**options)
    summary = {'status': 'planned', 'packageSha256': record['packageSha256'],
               'profileBeforeSha256': record['profileBeforeSha256'], 'profileAfterSha256': record['profileAfterSha256']}
    if not apply:
        return summary
    require(allow_paid is True, 'explicit_paid_inference_approval_required')
    profile_file, backup = map(local_path, (options['profile_file'], options['backup']))
    app_root, release = map(local_path, (record['appRoot'], record['releaseRoot']))
    def stopped_check():
        assert_stopped(profile, profile_file, app_root, release, stopped=stopped, processes=processes, listener=listener)
    stopped_check()
    with profile_lock(profile_file):
        check_hash(profile_file, record['profileBeforeSha256'])
        backup.mkdir(parents=True, exist_ok=False)
        pack.atomic_bytes(backup / 'profile.before.json', original)
        pack.atomic_bytes(backup / 'profile.after.json', updated)
        pack.atomic_bytes(backup / RECORD, canonical(record))
        check_hash(backup / 'profile.before.json', record['profileBeforeSha256'])
        check_hash(backup / 'profile.after.json', record['profileAfterSha256'])
        record_hash = sha_bytes(canonical(record))
        check_hash(backup / RECORD, record_hash)
        # Backups are durable before vault changes. A failed profile switch never
        # deletes a newly provisioned credential or silently restores an old key.
        stopped_check()
        action = ensure_credential(profile['profileId'], provision=provision, replace=replace, key_file=key_file)
        require(pack.verify_bundle(release)['packageSha256'] == record['packageSha256'], 'bundle_changed_before_activation')
        verify_acceptances(options['acceptances'], app_root, release, record['packageSha256'], options.get('edit_previews', False))
        check_hash(profile_file, record['profileBeforeSha256'])
        stopped_check()
        check_hash(profile_file, record['profileBeforeSha256'])
        check_hash(backup / RECORD, record_hash)
        try:
            (writer or pack.atomic_bytes)(profile_file, updated)
            check_hash(profile_file, record['profileAfterSha256'])
        except BaseException:
            # Atomic replacement may have completed before an I/O error was
            # reported. Restore only our exact after-image, never later edits.
            current = pack.digest(profile_file)
            if current == record['profileAfterSha256']:
                pack.atomic_bytes(profile_file, original)
            elif current != record['profileBeforeSha256']:
                raise Refused('activation_failed_with_profile_conflict') from None
            raise Refused('activation_failed_profile_restored') from None
    return dict(summary, status='activated', credentialAction=action,
                rollbackRecord=str(backup / RECORD), rollbackRecordSha256=record_hash)


def rollback(*, record_file, record_sha256, profile_file, app_root, apply=False, stopped=False,
             processes=None, listener=None):
    app_root, record_file, profile_file = normal_root(app_root), local_path(record_file), local_path(profile_file)
    require(record_file.name == RECORD, 'rollback_record_required')
    check_hash(record_file, record_sha256)
    record = read_json(record_file, 1024 * 1024)
    require(record.get('schemaVersion') == 1 and record.get('kind') == 'codex-normal-profile-only'
            and local_path(record['profileFile']) == profile_file and local_path(record['appRoot']) == app_root,
            'rollback_target_mismatch')
    before_file, after_file = record_file.parent / 'profile.before.json', record_file.parent / 'profile.after.json'
    check_hash(before_file, record['profileBeforeSha256'])
    check_hash(after_file, record['profileAfterSha256'])
    original, after = before_file.read_bytes(), after_file.read_bytes()
    require(sha_bytes(original) == record['profileBeforeSha256'] and sha_bytes(after) == record['profileAfterSha256'],
            'rollback_backup_changed')
    profile, updated = json_object(original), json_object(after)
    require('codexRuntime' not in profile and 'codexRuntime' in updated
            and {k: v for k, v in updated.items() if k != 'codexRuntime'} == profile,
            'rollback_is_not_profile_only')
    current = pack.digest(profile_file)
    require(current in {record['profileBeforeSha256'], record['profileAfterSha256']}, 'rollback_profile_conflict')
    if not apply:
        return {'status': 'rollback-planned'}
    release = local_path(record['releaseRoot'])
    assert_stopped(profile, profile_file, app_root, release, stopped=stopped, processes=processes, listener=listener)
    with profile_lock(profile_file):
        require(pack.digest(profile_file) == current, 'rollback_profile_conflict')
        check_hash(record_file, record_sha256)
        check_hash(before_file, record['profileBeforeSha256'])
        if current != record['profileBeforeSha256']:
            pack.atomic_bytes(profile_file, original)
        check_hash(profile_file, record['profileBeforeSha256'])
    return {'status': 'rolled-back', 'profileSha256': record['profileBeforeSha256']}


class SafeParser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **dict(kwargs, allow_abbrev=False))

    def error(self, message):
        self.exit(2, 'codex_profile_arguments_invalid; use --help\n')


def main(argv=None):
    parser = SafeParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True, parser_class=SafeParser)
    activation = commands.add_parser('activate')
    for name in ('release', 'backup'):
        activation.add_argument('--' + name, type=Path, required=True)
    activation.add_argument('--package-sha256', required=True)
    activation.add_argument('--profile-sha256', required=True)
    activation.add_argument('--acceptance', nargs=3, action='append', required=True,
                            metavar=('REPORT', 'REPORT_SHA256', 'EVIDENCE_SHA256'))
    activation.add_argument('--enable-edit-previews', dest='edit_previews', action='store_true')
    activation.add_argument('--allow-paid-inference', dest='allow_paid', action='store_true')
    activation.add_argument('--provision-credential', dest='provision', action='store_true')
    activation.add_argument('--replace-credential', dest='replace', action='store_true')
    activation.add_argument('--api-key-file', dest='key_file', type=Path)
    reversal = commands.add_parser('rollback')
    reversal.add_argument('--record-file', type=Path, required=True)
    reversal.add_argument('--record-sha256', required=True)
    for command in (activation, reversal):
        command.add_argument('--app-root', type=Path, default=ROOT)
        command.add_argument('--profile-file', type=Path, required=True)
        command.add_argument('--apply', action='store_true')
        command.add_argument('--desktop-stopped', dest='stopped', action='store_true')
    args = vars(parser.parse_args(argv))
    command = args.pop('command')
    for name in ('app_root', 'release', 'backup', 'profile_file', 'record_file', 'key_file'):
        if args.get(name) is not None:
            args[name] = args[name].absolute()
    if command == 'activate':
        args['acceptances'] = [(Path(file).absolute(), report_hash, evidence_hash)
                               for file, report_hash, evidence_hash in args.pop('acceptance')]
    try:
        result = activate(**args) if command == 'activate' else rollback(**args)
        print(json.dumps(result))
        return 0
    except Exception as error:
        print(json.dumps({'status': 'refused', 'code': str(error) if isinstance(error, Refused) else 'codex_profile_operation_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
