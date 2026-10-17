"""Prepare/verify pinned dependency bundles; retain diagnostic snapshot tooling.

No downloads, credential reads, inference, Electron launch or layout migration.
Promotion and rollback are dry runs unless --apply --desktop-stopped are supplied.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from desktop.runtime.application_profile import load_application_profile
from desktop.runtime.codex_config import (
    MODEL, PACKAGE, PINS, dependency_files as inventory_dependencies,
    dependency_versions, digest, verify_dependency_package,
)
from desktop.runtime.codex_credentials import credential_target
from desktop.runtime.profile import canonical, local_path, read_json, write_exclusive

RELEASE = 'desktop-codex-release.json'
BUNDLE = 'desktop-codex-bundle.json'
JOURNAL = 'codex-deployment.json'
DEPS = Path('.runtime/codex-pilot-deps')
METADATA = {'desktop-checkpoint.json', 'desktop-source-manifest.json', RELEASE}


@lru_cache(maxsize=1)
def snapshot_helper():
    spec = importlib.util.spec_from_file_location('codex_desktop_snapshot', ROOT / 'desktop/tools/prepare-snapshot.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def within(path, root):
    return path == root or root in path.parents


def separate(*paths):
    if any(within(a, b) or within(b, a) for i, a in enumerate(paths) for b in paths[i + 1:]):
        raise ValueError('desktop_codex_paths_overlap')


def relative_path(value):
    if (not isinstance(value, str) or not value or '\\' in value or ':' in value
            or any(part in {'', '.', '..'} for part in value.split('/'))):
        raise ValueError('desktop_codex_manifest_path_invalid')
    relative = PurePosixPath(value)
    if relative.is_absolute() or any(part.lower().startswith('.env') for part in relative.parts):
        raise ValueError('desktop_codex_manifest_path_invalid')
    return Path(*relative.parts)


def dependency_files(root):
    return inventory_dependencies(root, allow_cache=True)


def prepare_bundle(source, destination, dependencies, *, probe=None):
    source, destination, dependencies = map(local_path, (source, destination, dependencies))
    if dependencies != source / DEPS:
        raise ValueError('desktop_codex_tested_dependency_root_required')
    separate(source, destination)
    if destination.exists():
        raise ValueError('desktop_codex_new_bundle_required')
    versions, records = dependency_versions(dependencies), dependency_files(dependencies)
    (probe or probe_binary)(dependencies / 'codex_cli_bin/bin/codex.exe')
    destination.mkdir(parents=True)
    for record in records:
        relative = relative_path(record['path'])
        target = destination / DEPS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with (dependencies / relative).open('rb') as old, target.open('xb') as new:
            shutil.copyfileobj(old, new)
        if digest(target) != record['sha256']:
            raise ValueError('desktop_codex_dependency_changed_during_copy')
    if dependency_files(dependencies) != records:
        raise ValueError('desktop_codex_dependency_changed_during_copy')
    write_exclusive(destination / DEPS / PACKAGE, {
        'schemaVersion': 1, 'pins': PINS, 'versions': versions, 'files': records,
        'pythonTag': sys.implementation.cache_tag, 'platform': sys.platform})
    package_hash = digest(destination / DEPS / PACKAGE)
    write_exclusive(destination / BUNDLE, {
        'schemaVersion': 1, 'kind': 'codex-dependencies', 'pins': PINS, 'model': MODEL,
        'dependencyPath': DEPS.as_posix(), 'packageSha256': package_hash})
    verify_bundle(destination)
    return {'status': 'prepared', 'dependencyRoot': str(destination / DEPS),
            'packageSha256': package_hash, 'bundleSha256': digest(destination / BUNDLE)}


def verify_bundle(root):
    root = local_path(root)
    value = read_json(local_path(root / BUNDLE))
    if (set(value) != {'schemaVersion', 'kind', 'pins', 'model', 'dependencyPath', 'packageSha256'}
            or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
            or value['kind'] != 'codex-dependencies' or value['pins'] != PINS
            or value['model'] != MODEL or value['dependencyPath'] != DEPS.as_posix()):
        raise ValueError('desktop_codex_bundle_invalid')
    verify_dependency_package(root / DEPS, value['packageSha256'])
    return value


def probe_binary(binary):
    env = {k: v for k, v in os.environ.items()
           if k.upper() in {'SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP', 'PATHEXT'}}
    result = subprocess.run([str(binary), '--version'], capture_output=True, env=env, shell=False,
                            timeout=15, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    if result.returncode or result.stdout.strip() != b'codex-cli 0.162.1':
        raise ValueError('desktop_codex_binary_version_mismatch')


def prepare(source, destination, dependencies, *, probe=probe_binary):
    source, destination, dependencies = map(local_path, (source, destination, dependencies))
    if dependencies != source / DEPS:
        raise ValueError('desktop_codex_tested_dependency_root_required')
    separate(source, destination)
    versions = dependency_versions(dependencies)
    records = dependency_files(dependencies)
    probe(dependencies / 'codex_cli_bin/bin/codex.exe')
    snapshot_helper().prepare_snapshot(source, destination)
    for record in records:
        relative = relative_path(record['path'])
        target = destination / DEPS / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with (dependencies / relative).open('rb') as old, target.open('xb') as new:
            shutil.copyfileobj(old, new)
        if digest(target) != record['sha256']:
            raise ValueError('desktop_codex_dependency_changed_during_copy')
    if dependency_files(dependencies) != records:
        raise ValueError('desktop_codex_dependency_changed_during_copy')
    package = {'schemaVersion': 1, 'pins': PINS, 'versions': versions, 'files': records,
               'pythonTag': sys.implementation.cache_tag, 'platform': sys.platform}
    write_exclusive(destination / DEPS / PACKAGE, package)
    manifest = read_json(destination / 'desktop-source-manifest.json', 64 * 1024 * 1024)
    files = [{'path': r['path'], 'bytes': r['bytes'], 'sha256': r['sha256']} for r in manifest]
    files.extend(dict(r, path=(DEPS / r['path']).as_posix()) for r in records)
    for relative in ('desktop-checkpoint.json', 'desktop-source-manifest.json', (DEPS / PACKAGE).as_posix()):
        file = destination / relative
        files.append({'path': relative, 'bytes': file.stat().st_size, 'sha256': digest(file)})
    write_exclusive(destination / RELEASE, {'schemaVersion': 1, 'pins': PINS, 'model': MODEL,
                    'files': sorted(files, key=lambda r: r['path'])})
    verify_release(destination)
    return {'status': 'prepared', 'files': len(files), 'releaseSha256': digest(destination / RELEASE)}


def allowed_build_path(relative):
    if relative.as_posix() in METADATA:
        return True
    if within(relative, DEPS):
        return True
    return snapshot_helper().relative_is_allowed(relative, tracked=True)


def verified_records(root, records):
    if not isinstance(records, list) or not records or len(records) > 100000:
        raise ValueError('desktop_codex_manifest_invalid')
    seen = set()
    for record in records:
        relative = relative_path(record['path'])
        name = relative.as_posix().casefold()
        if name in seen or not allowed_build_path(relative):
            raise ValueError('desktop_codex_manifest_path_invalid')
        seen.add(name)
        file = local_path(root / relative)
        if not within(file, root) or not file.is_file() or file.stat().st_size != record['bytes'] or digest(file) != record['sha256']:
            raise ValueError('desktop_codex_release_hash_mismatch')


def verify_release(root):
    root = local_path(root)
    value = read_json(root / RELEASE, 64 * 1024 * 1024)
    if value.get('schemaVersion') != 1 or value.get('pins') != PINS or value.get('model') != MODEL:
        raise ValueError('desktop_codex_release_invalid')
    verified_records(root, value['files'])
    checkpoint = read_json(root / 'desktop-checkpoint.json')
    separate(root, local_path(checkpoint['source']))
    if checkpoint.get('sourceManifestSha256') != digest(root / 'desktop-source-manifest.json'):
        raise ValueError('desktop_codex_snapshot_manifest_mismatch')
    package = read_json(root / DEPS / PACKAGE, 16 * 1024 * 1024)
    if (package.get('pins') != PINS or package.get('schemaVersion') != 1
            or package.get('versions') != dependency_versions(root / DEPS)
            or package.get('pythonTag') != sys.implementation.cache_tag or package.get('platform') != sys.platform
            or package.get('files') != dependency_files(root / DEPS)):
        raise ValueError('desktop_codex_package_mismatch')
    # The release must include every source and optional dependency record.
    expected = {r['path'] for r in read_json(root / 'desktop-source-manifest.json', 64 * 1024 * 1024)}
    expected.update((DEPS / r['path']).as_posix() for r in package['files'])
    expected.update({'desktop-checkpoint.json', 'desktop-source-manifest.json', (DEPS / PACKAGE).as_posix()})
    if expected != {r['path'] for r in value['files']}:
        raise ValueError('desktop_codex_release_inventory_mismatch')
    return value


def atomic_bytes(file, content):
    file = local_path(file)
    file.parent.mkdir(parents=True, exist_ok=True)
    pending = file.with_name('.codex-' + uuid.uuid4().hex + '.tmp')
    # Python's low-level Windows replace/open APIs still need extended spellings
    # for long dependency paths. Validate the ordinary local path before adding it.
    io_file = Path('\\\\?\\' + str(file)) if os.name == 'nt' else file
    io_pending = Path('\\\\?\\' + str(pending)) if os.name == 'nt' else pending
    try:
        with io_pending.open('xb') as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(io_pending, io_file)
    finally:
        if io_pending.exists():
            io_pending.unlink()


def file_hash(file):
    return digest(file) if file.is_file() else None


def plan_promotion(release, build, profile_file, backup, *, edit_previews=False):
    release, build, profile_file, backup = map(local_path, (release, build, profile_file, backup))
    separate(release, build, backup)
    if backup.exists():
        raise ValueError('desktop_codex_new_backup_required')
    value = verify_release(release)
    checkpoint = read_json(build / 'desktop-checkpoint.json')
    separate(build, local_path(checkpoint['source']))
    separate(backup, local_path(checkpoint['source']))
    profile = load_application_profile(profile_file).value
    for name in ('dataRoot', 'facilityRoot', 'libraryRoot'):
        store = local_path(profile[name])
        separate(store, release)
        separate(store, build)
        separate(store, backup)
    if within(profile_file, build) or within(profile_file, release) or within(profile_file, backup):
        raise ValueError('desktop_codex_profile_overlaps_build')
    updated = dict(profile, codexRuntime={
        'schemaVersion': 1, 'model': MODEL, 'allowPaidInference': True, 'editPreviews': edit_previews,
        'dependencyRoot': str(build / DEPS), 'binary': str(build / DEPS / 'codex_cli_bin/bin/codex.exe'),
        'packageSha256': digest(release / DEPS / PACKAGE),
        'pilotRoot': str(Path(profile['dataRoot']) / 'codex-pilot'),
        'credentialTarget': credential_target(profile['profileId'])})
    records = list(value['files']) + [{'path': RELEASE, 'sha256': digest(release / RELEASE), 'bytes': (release / RELEASE).stat().st_size}]
    changes = []
    for record in records:
        file = local_path(build / relative_path(record['path']))
        if not within(file, build) or (file.exists() and not file.is_file()):
            raise ValueError('desktop_codex_install_target_invalid')
        changes.append({'path': record['path'], 'before': file_hash(file), 'after': record['sha256']})
    # A previous Codex dependency tree must be exact: overlaying different versions
    # would silently leave importable stale packages behind. Use a new build instead.
    if (build / DEPS).exists():
        old_names = {r['path'] for r in dependency_files(build / DEPS)}
        new_names = {r['path'] for r in read_json(release / DEPS / PACKAGE, 16 * 1024 * 1024)['files']}
        if old_names - new_names:
            raise ValueError('desktop_codex_stale_dependencies_require_new_build')
    return {'schemaVersion': 1, 'status': 'planned', 'build': str(build), 'profileFile': str(profile_file),
            'release': str(release), 'releaseSha256': digest(release / RELEASE),
            'changes': changes, 'profileBefore': digest(profile_file),
            'profileAfter': hashlib.sha256(canonical(updated)).hexdigest()}, updated


def promote(release, build, profile_file, backup, *, apply=False, desktop_stopped=False,
            allow_paid=False, edit_previews=False, expected_sha256=None, writer=atomic_bytes):
    if not allow_paid:
        raise ValueError('desktop_codex_explicit_billing_approval_required')
    journal, updated = plan_promotion(release, build, profile_file, backup, edit_previews=edit_previews)
    if not apply:
        return {'status': 'planned', 'files': len(journal['changes']), 'releaseSha256': journal['releaseSha256']}
    if not desktop_stopped:
        raise ValueError('desktop_codex_close_desktop_before_promotion')
    if expected_sha256 != journal['releaseSha256']:
        raise ValueError('desktop_codex_approved_release_hash_required')
    release, build, profile_file, backup = map(local_path, (release, build, profile_file, backup))
    backup.mkdir()
    # Finish and hash-check every backup before replacing any installed byte.
    for change in journal['changes']:
        relative = relative_path(change['path'])
        file = local_path(build / relative)
        if file_hash(file) != change['before']:
            raise ValueError('desktop_codex_build_changed_before_backup')
        if change['before'] is not None:
            target = backup / 'build' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(file, target)
            if digest(target) != change['before']:
                raise ValueError('desktop_codex_backup_hash_mismatch')
    shutil.copyfile(profile_file, backup / 'profile.before.json')
    if digest(backup / 'profile.before.json') != journal['profileBefore']:
        raise ValueError('desktop_codex_profile_changed_before_backup')
    write_exclusive(backup / 'profile.after.json', updated)
    write_exclusive(backup / JOURNAL, journal)
    try:
        verify_release(release)
        for change in journal['changes']:
            relative = relative_path(change['path'])
            file = local_path(build / relative)
            if file_hash(file) != change['before']:
                raise ValueError('desktop_codex_build_changed_during_promotion')
            writer(file, (release / relative).read_bytes())
        if digest(profile_file) != journal['profileBefore']:
            raise ValueError('desktop_codex_profile_changed_during_promotion')
        # Profile enablement is last, after all validated runtime code/deps.
        writer(profile_file, canonical(updated))
        verify_release(build)
        journal['status'] = 'promoted'
        atomic_bytes(backup / JOURNAL, canonical(journal))
    except Exception:
        rollback(backup, apply=True, desktop_stopped=True)
        raise ValueError('desktop_codex_promotion_failed_rolled_back') from None
    return {'status': 'promoted', 'files': len(journal['changes']), 'rollbackJournal': str(backup / JOURNAL)}


def rollback(backup, *, apply=False, desktop_stopped=False):
    backup = local_path(backup)
    journal = read_json(backup / JOURNAL, 64 * 1024 * 1024)
    build, profile_file = map(local_path, (journal['build'], journal['profileFile']))
    separate(build, backup)
    if within(profile_file, build) or within(profile_file, backup):
        raise ValueError('desktop_codex_rollback_target_invalid')
    profile_before = backup / 'profile.before.json'
    if digest(profile_before) != journal['profileBefore']:
        raise ValueError('desktop_codex_rollback_backup_changed')
    original = read_json(profile_before)
    for name in ('dataRoot', 'facilityRoot', 'libraryRoot'):
        separate(local_path(original[name]), build)
        separate(local_path(original[name]), backup)
    changes = []
    seen = set()
    for change in journal['changes']:
        relative = relative_path(change['path'])
        if not allowed_build_path(relative) or relative.as_posix().casefold() in seen:
            raise ValueError('desktop_codex_rollback_target_invalid')
        seen.add(relative.as_posix().casefold())
        file, saved = local_path(build / relative), local_path(backup / 'build' / relative)
        if change['before'] is not None and file_hash(saved) != change['before']:
            raise ValueError('desktop_codex_rollback_backup_changed')
        if file_hash(file) not in {change['before'], change['after']}:
            raise ValueError('desktop_codex_rollback_conflict')
        changes.append((file, saved, change))
    if digest(profile_file) not in {journal['profileBefore'], journal['profileAfter']}:
        raise ValueError('desktop_codex_rollback_profile_conflict')
    if not apply:
        return {'status': 'rollback-planned', 'files': len(changes)}
    if not desktop_stopped:
        raise ValueError('desktop_codex_close_desktop_before_rollback')
    atomic_bytes(profile_file, profile_before.read_bytes())
    for file, saved, change in reversed(changes):
        # Recheck immediately before each replacement; later user changes are not ours.
        if file_hash(file) not in {change['before'], change['after']}:
            raise ValueError('desktop_codex_rollback_conflict')
        if change['before'] is None:
            if file.exists():
                if not within(file, build):
                    raise ValueError('desktop_codex_rollback_target_invalid')
                file.unlink()
        else:
            atomic_bytes(file, saved.read_bytes())
    journal['status'] = 'rolled-back'
    atomic_bytes(backup / JOURNAL, canonical(journal))
    return {'status': 'rolled-back', 'files': len(changes)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    prepare_parser = commands.add_parser('prepare')
    prepare_parser.add_argument('--source', type=Path, required=True)
    prepare_parser.add_argument('--destination', type=Path, required=True)
    prepare_parser.add_argument('--dependency-dir', type=Path, required=True)
    bundle_parser = commands.add_parser('prepare-bundle', help='Copy dependencies only; preserve the normal checkout and all stores')
    bundle_parser.add_argument('--source', type=Path, required=True)
    bundle_parser.add_argument('--destination', type=Path, required=True)
    bundle_parser.add_argument('--dependency-dir', type=Path, required=True)
    bundle_verify_parser = commands.add_parser('verify-bundle')
    bundle_verify_parser.add_argument('--release', type=Path, required=True)
    verify_parser = commands.add_parser('verify')
    verify_parser.add_argument('--release', type=Path, required=True)
    promote_parser = commands.add_parser('promote')
    for name in ('release', 'build', 'profile-file', 'backup'):
        promote_parser.add_argument('--' + name, type=Path, required=True)
    promote_parser.add_argument('--allow-paid-inference', action='store_true')
    promote_parser.add_argument('--enable-edit-previews', action='store_true')
    promote_parser.add_argument('--release-sha256', help='Exact reviewed release manifest hash; required with --apply')
    rollback_parser = commands.add_parser('rollback')
    rollback_parser.add_argument('--backup', type=Path, required=True)
    for command in (promote_parser, rollback_parser):
        command.add_argument('--apply', action='store_true')
        command.add_argument('--desktop-stopped', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare(args.source, args.destination, args.dependency_dir)
        elif args.command == 'prepare-bundle':
            result = prepare_bundle(args.source, args.destination, args.dependency_dir)
        elif args.command == 'verify-bundle':
            value = verify_bundle(args.release)
            result = {'status': 'verified', 'packageSha256': value['packageSha256'],
                      'bundleSha256': digest(args.release / BUNDLE)}
        elif args.command == 'verify':
            value = verify_release(args.release)
            result = {'status': 'verified', 'files': len(value['files']), 'releaseSha256': digest(args.release / RELEASE)}
        elif args.command == 'promote':
            result = promote(args.release, args.build, args.profile_file, args.backup, apply=args.apply,
                             desktop_stopped=args.desktop_stopped, allow_paid=args.allow_paid_inference,
                             edit_previews=args.enable_edit_previews, expected_sha256=args.release_sha256)
        else:
            result = rollback(args.backup, apply=args.apply, desktop_stopped=args.desktop_stopped)
        print(json.dumps(result))
        return 0
    except Exception:
        # Never echo arbitrary exception text, profile values, process output or env.
        print(json.dumps({'status': 'refused', 'code': 'desktop_codex_deployment_failed'}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
