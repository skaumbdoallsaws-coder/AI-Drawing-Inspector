"""Opt-in owned desktop backend using the actual application and private stdin.

No token is accepted through argv, environment variables, URLs or HTTP shutdown.
This runtime currently serves only explicitly isolated developer stores.
"""
from __future__ import annotations
import sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import argparse
import asyncio
from contextlib import asynccontextmanager
from copy import deepcopy
import json
import os
import re
import site
import threading
import time
import uuid

from desktop.runtime.profile import load_profile, local_path

SAFE_ENV = {'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'PATHEXT', 'NUMBER_OF_PROCESSORS', 'PROCESSOR_ARCHITECTURE', 'PROCESSOR_IDENTIFIER', 'OS'}
CURRENT_PHASE = 'private-bootstrap'
_STARTUP_STARTED = time.monotonic()
_PHASE_STARTED = _STARTUP_STARTED
_CHECKPOINT_SEQUENCE = 0
_IMPORT_DIAGNOSTICS = None
_IMPORT_DIAGNOSTICS_INSTANCE = None
_DIAGNOSTIC_ERRORS = set()


def emit(kind, value):
    sys.stdout.write('INSPECTORPRO_DESKTOP_RUNTIME_' + kind + ' ' + json.dumps(value, separators=(',', ':')) + '\n')
    sys.stdout.flush()


def diagnostic_action(operation, *args):
    """Evidence collection must not replace readiness, failure, or cleanup."""
    if _IMPORT_DIAGNOSTICS is None: return False
    try:
        method = {'start': 'start', 'bind': 'bind', 'stop': 'stop', 'capture-shutdown': 'capture_shutdown'}[operation]
        getattr(_IMPORT_DIAGNOSTICS, method)(*args)
        return True
    except Exception as error:
        signature = (operation, type(error).__name__)
        if signature not in _DIAGNOSTIC_ERRORS:
            _DIAGNOSTIC_ERRORS.add(signature)
            try:
                emit('DIAGNOSTIC_ERROR', {'schemaVersion': 1, 'instanceId': _IMPORT_DIAGNOSTICS_INSTANCE,
                    'processId': os.getpid(), 'operation': operation, 'errorType': type(error).__name__})
            except (OSError, ValueError): pass
        return False


def checkpoint(phase, instance_id):
    global CURRENT_PHASE, _PHASE_STARTED, _CHECKPOINT_SEQUENCE
    observed = time.monotonic()
    previous = CURRENT_PHASE
    duration = max(0, (observed - _PHASE_STARTED) * 1000)
    CURRENT_PHASE = phase
    _PHASE_STARTED = observed
    _CHECKPOINT_SEQUENCE += 1
    emit('CHECKPOINT', {'schemaVersion': 1, 'phase': phase, 'instanceId': instance_id, 'processId': os.getpid(),
                       'sequence': _CHECKPOINT_SEQUENCE, 'elapsedMs': max(0, (observed - _STARTUP_STARTED) * 1000),
                       'previousPhase': previous, 'previousPhaseDurationMs': duration})


def bootstrap(stream):
    raw = stream.readline(4097)
    try:
        value = json.loads(raw)
        if (len(raw) > 4096 or not raw.endswith(b'\n') or set(value) != {'schemaVersion', 'credential', 'instanceId'}
                or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
                or not isinstance(value['credential'], str) or not re.fullmatch(r'[a-f0-9]{64}', value['credential'])
                or str(uuid.UUID(value['instanceId'])) != value['instanceId']):
            raise ValueError()
    except Exception:
        raise ValueError('A valid private desktop launch handshake is required') from None
    return value


class PrivateControl:
    def __init__(self, stream):
        self.stream, self.stop = stream, threading.Event()
        self.request_id, self.reason, self.invalid = None, None, False

    def read(self):
        while not self.stop.is_set():
            raw = self.stream.readline(4097)
            if not raw:
                self.reason = 'private-channel-eof'; self.stop.set(); return
            try:
                value = json.loads(raw)
                if (len(raw) > 4096 or not raw.endswith(b'\n') or set(value) != {'schemaVersion', 'command', 'requestId'}
                        or type(value['schemaVersion']) is not int or value['schemaVersion'] != 1
                        or value['command'] != 'shutdown' or str(uuid.UUID(value['requestId'])) != value['requestId']):
                    raise ValueError()
                self.request_id, self.reason = value['requestId'], 'private-channel-shutdown'
            except Exception:
                self.reason, self.invalid = 'invalid-private-control', True
            self.stop.set()
            diagnostic_action('capture-shutdown')


def configure_environment(profile):
    parent = dict(os.environ)
    env = {key: value for key, value in parent.items() if key.upper() in SAFE_ENV}
    system = Path(parent.get('SYSTEMROOT', parent.get('SystemRoot', 'C:/Windows')))
    data = profile.data
    env.update(PATH=os.pathsep.join([str(Path(sys.executable).parent), str(system / 'System32'), str(system)]),
        PYTHONDONTWRITEBYTECODE='1', PYTHON_DOTENV_DISABLED='1', PYTHONUNBUFFERED='1',
        TEMP=str(data / 'temp'), TMP=str(data / 'temp'), LOCALAPPDATA=str(data / 'localappdata'), APPDATA=str(data / 'appdata'),
        INSPECTORPRO_LIBRARY_DIR=str(data / 'library'), INSPECTORPRO_FACILITY_LAYOUT_ROOT=str(data / 'facility'),
        INSPECTORPRO_METRICS_DB=str(data / 'metrics.sqlite'), INSPECTORPRO_MEMORY_DB_PATH=str(data / 'memory.sqlite'),
        INSPECTORPRO_MEMORY_V1_MODE='off', INSPECTORPRO_CHAT_FEEDBACK_DB_PATH=str(data / 'feedback.sqlite'),
        INSPECTORPRO_PARTS_MANUAL_ROOT=str(data / 'parts-manual'), INSPECTORPRO_OPERATIONS_MANUAL_ROOT=str(data / 'operations-manual'),
        INSPECTORPRO_SPECIFICATION_SHEET_ROOT=str(data / 'specification-sheets'), INSPECTORPRO_WORK_INSTRUCTION_ROOT=str(data / 'work-instructions'),
        HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', INSPECTORPRO_FACILITY_PRIVATE_ASSETS='0',
        INSPECTORPRO_FACILITY_LAYOUT_VIEWER_V2='1', INSPECTORPRO_INDUSTRIAL_ASSET_LIBRARY='1',
        INSPECTORPRO_FACILITY_LAYOUT_CONSTRUCTION_SAGE='0')
    os.environ.clear(); os.environ.update(env)
    sys.dont_write_bytecode = True
    # sys.path already contains the interpreter's configured user site; retain
    # installed dependency paths, without inheriting a user's environment file.
    for item in [*site.getsitepackages(), site.getusersitepackages()]:
        if Path(item).is_dir() and item not in sys.path: sys.path.append(item)
    from ai_inspector.facility_layout.feature_flags import FACILITY_LAYOUT_FEATURE_FLAGS, FACILITY_DESIGN_LOOP_FEATURE_FLAGS
    for name in FACILITY_LAYOUT_FEATURE_FLAGS: os.environ[name] = '1'
    for name in FACILITY_DESIGN_LOOP_FEATURE_FLAGS:
        os.environ[name] = '0' if name.endswith(('_LAB', '_SAGE')) else '1'


def install_runtime_guard(data):
    """Python defense in depth, not a replacement for OS process isolation."""
    def check(raw):
        if isinstance(raw, (str, bytes, os.PathLike)):
            target = local_path(Path(os.path.abspath(os.fsdecode(raw))))
            if target != data and data not in target.parents:
                raise PermissionError('Desktop runtime write is outside its selected isolated store')
    def audit(event, args):
        if event == 'open':
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(flag in mode for flag in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)):
                check(args[0])
        elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.utime', 'sqlite3.connect'}:
            if args[0] != ':memory:': check(args[0])
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            check(args[0]); check(args[1])
        elif event in {'subprocess.Popen', 'os.system', 'os.posix_spawn'}:
            raise PermissionError('Desktop provider and native-helper capabilities are not accepted')
    sys.addaudithook(audit)


def configure_assets(server, profile):
    if profile.layout_id is None: return
    from starlette.routing import Mount
    from starlette.staticfiles import StaticFiles
    from ai_inspector.facility_layout.host import build_private_local_asset_catalog, LOCAL_ASSET_CATALOG
    root = local_path(profile.data / 'asset-project')
    if not root.is_dir(): raise ValueError('Selected isolated facility asset store is missing')
    if os.name == 'nt': root = Path('\\\\?\\' + str(root))
    catalog = build_private_local_asset_catalog(root)
    host = server._FACILITY_LAYOUT_HOST
    host._catalog = {item['assetId']: deepcopy(item) for item in catalog}
    host._asset_versions = {(item['assetId'], item['assetDefinitionRevision']): deepcopy(item) for item in (*LOCAL_ASSET_CATALOG, *catalog)}
    server.app.router.routes.insert(0, Mount('/generated/industrial_assets', StaticFiles(directory=str(root / 'generated/industrial_assets')), name='desktop-isolated-assets'))


async def serve(profile, private, control, *, application=False):
    checkpoint('uvicorn-import', private['instanceId'])
    import uvicorn
    checkpoint('application-import', private['instanceId'])
    import_diagnostic = None
    if application:
        try:
            from desktop.runtime.startup_diagnostics import CooperativeTracebackHandler
            import_diagnostic = CooperativeTracebackHandler()
            import_diagnostic.dump_traceback_later(20, repeat=True, file=sys.stderr)
        except Exception as error:
            emit('DIAGNOSTIC_ERROR', {'schemaVersion': 1, 'instanceId': private['instanceId'],
                'processId': os.getpid(), 'operation': 'start', 'errorType': type(error).__name__})
    try:
        import server
    finally:
        if import_diagnostic is not None:
            try: import_diagnostic.cancel_dump_traceback_later()
            except Exception as error:
                emit('DIAGNOSTIC_ERROR', {'schemaVersion': 1, 'instanceId': private['instanceId'],
                    'processId': os.getpid(), 'operation': 'stop', 'errorType': type(error).__name__})
    checkpoint('application-store-validation', private['instanceId'])
    if application:
        from desktop.runtime.application_boundary import ApplicationBoundary as Boundary
        if (local_path(server.LIBRARY_DIR) != Path(profile.value['libraryRoot'])
                or local_path(server._FACILITY_LAYOUT_HOST.root) != Path(profile.value['facilityRoot'])):
            raise ValueError('Application resolved a different authoritative store')
    else:
        from desktop.runtime.boundary import DesktopBoundary as Boundary
        if local_path(server.LIBRARY_DIR) != profile.data / 'library' or local_path(server._FACILITY_LAYOUT_HOST.root) != profile.data / 'facility':
            raise ValueError('Application resolved a different authoritative store')
        configure_assets(server, profile)
    checkpoint('application-assets-configured', private['instanceId'])
    original = server.app.router.lifespan_context
    lifecycle = {'started': False, 'completed': False, 'resourcesClosed': False, 'cleanupErrors': []}
    @asynccontextmanager
    async def managed_lifespan(app):
        try:
            async with original(app):
                lifecycle['started'] = True
                yield
            lifecycle['completed'] = True
        finally:
            for close in (server._FACILITY_LAYOUT_HOST.close, server._reset_agent_memory_runtime_for_tests,
                          lambda: server._SKILL_ROUTE_SHADOW_EXECUTOR.shutdown(wait=True, cancel_futures=True),
                          lambda: server._VIEWPORT_INTENT_EXECUTOR.shutdown(wait=True, cancel_futures=True)):
                try: close()
                except Exception as error: lifecycle['cleanupErrors'].append(type(error).__name__)
            lifecycle['resourcesClosed'] = lifecycle['completed'] and not lifecycle['cleanupErrors']
    server.app.router.lifespan_context = managed_lifespan
    boundary = Boundary(server.app, profile, private['credential'], private['instanceId'], server._FACILITY_LAYOUT_HOST)
    config = uvicorn.Config(boundary, host='127.0.0.1', port=int(profile.origin.rsplit(':', 1)[1]),
                            lifespan='on', log_level='warning', access_log=False, timeout_graceful_shutdown=10)
    runtime_server = uvicorn.Server(config)
    ready = False
    async def supervise():
        nonlocal ready
        while True:
            if runtime_server.started and not ready:
                # Uvicorn sets started only after lifespan startup and listening.
                ready = True
                checkpoint('application-ready', private['instanceId'])
                diagnostic_action('stop')
                emit('READY', boundary.runtime())
            if ready and control.stop.is_set():
                runtime_server.should_exit = True
                return
            await asyncio.sleep(0.025)
    monitor = asyncio.create_task(supervise())
    try:
        checkpoint('application-listener-starting', private['instanceId'])
        await runtime_server.serve()
    finally:
        monitor.cancel()
        await asyncio.gather(monitor, return_exceptions=True)
        emit('SHUTDOWN', {'schemaVersion': 1, 'instanceId': private['instanceId'], 'processId': os.getpid(),
                         'requestId': control.request_id, 'reason': control.reason or 'server-exit',
                         'readyWasEmitted': ready, 'resourcesClosed': lifecycle['resourcesClosed'],
                         'lifespanStopped': lifecycle['completed'], 'cleanupErrors': lifecycle['cleanupErrors']})
    if not ready or not lifecycle['resourcesClosed'] or control.invalid:
        raise RuntimeError('Desktop backend did not complete accepted startup and resource cleanup')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--profile-file', type=Path, required=True)
    args = parser.parse_args()
    global _IMPORT_DIAGNOSTICS, _IMPORT_DIAGNOSTICS_INSTANCE
    diagnostic_started = False
    if sys._xoptions.get('importtime'):
        from desktop.runtime.startup_diagnostics import StartupImportDiagnostics
        _IMPORT_DIAGNOSTICS = StartupImportDiagnostics()
        diagnostic_started = diagnostic_action('start')
    try:
        private = bootstrap(sys.stdin.buffer)
        _IMPORT_DIAGNOSTICS_INSTANCE = private['instanceId']
        checkpoint('profile-validation', private['instanceId'])
        profile = load_profile(args.profile_file, ROOT)
        if diagnostic_started:
            diagnostic_action('bind', profile.data, private['instanceId'], os.getpid())
        emit('STARTING', {'schemaVersion': 1, 'instanceId': private['instanceId'], 'processId': os.getpid(), 'profileId': profile.value['profileId']})
        configure_environment(profile)
        checkpoint('environment-configured', private['instanceId'])
        os.chdir(ROOT)
        install_runtime_guard(profile.data)
        control = PrivateControl(sys.stdin.buffer)
        threading.Thread(target=control.read, name='desktop-private-control', daemon=True).start()
        asyncio.run(serve(profile, private, control))
    finally:
        diagnostic_action('stop')


if __name__ == '__main__':
    try: main()
    except BaseException as error:
        # Fixed class/code only: arbitrary exception text can contain request or
        # configuration values. Detailed backend import logs carry no credential.
        emit('FAILED', {'schemaVersion': 1, 'code': 'desktop_runtime_failed', 'phase': CURRENT_PHASE, 'errorType': type(error).__name__})
        raise SystemExit(1)
