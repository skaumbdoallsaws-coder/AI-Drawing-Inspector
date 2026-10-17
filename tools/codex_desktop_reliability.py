"""Test-only supervision for native Codex load, interruption and restart checks."""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import tomllib
from urllib.parse import urlparse

import psutil

FLAGS = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0


def write_json(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2), encoding='utf-8')
    temporary.replace(path)


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def clean_desktop_shutdown(receipt):
    return (receipt.get('forced') is False and receipt.get('exitCode') == 0
            and all(receipt.get(key) is True for key in
                    ('terminationConfirmed', 'stdioClosed', 'resourcesClosed')))


def alive(process):
    try:
        return process.is_running() and process.status() != psutil.STATUS_ZOMBIE
    except psutil.NoSuchProcess:
        return False


def read_audit(output):
    with sqlite3.connect(output / 'codex-pilot/pilot.sqlite', timeout=1) as db:
        journal = [{'turnId': row[0], 'status': row[1], 'binding': row[2],
                    'result': json.loads(row[3] or '{}')}
                   for row in db.execute('SELECT turn_id,status,binding,result FROM turns ORDER BY updated')]
        sessions = db.execute('SELECT COUNT(*) FROM sessions').fetchone()[0]
    with sqlite3.connect(output / 'memory.sqlite', timeout=1) as db:
        memory = [{'turnId': row[0], 'status': row[1], 'errorCode': row[2],
                   'hasManifest': bool(row[3]), 'model': json.loads(row[4]),
                   'conversationId': row[5], 'agentSessionId': row[6]}
                  for row in db.execute('SELECT client_turn_id,status,error_code,context_manifest_id,'
                      'model_metadata_json,conversation_id,agent_session_id FROM memory_turns ORDER BY sequence')]
    return journal, memory, sessions


class OwnedRuntimeMonitor:
    def __init__(self, child, binary, output, round_output):
        self.root = psutil.Process(child.pid)
        self.binary = binary.resolve()
        self.output, self.round_output = output, round_output
        self.known = {}
        self.runtimes = {}
        self.affinities = {}
        self.ports = set()
        self.handled = set()
        self.active_control = None
        self.controls = []

    def observe(self):
        try:
            descendants = self.root.children(recursive=True)
        except psutil.NoSuchProcess:
            descendants = []
        for process in descendants:
            try:
                self.known[(process.pid, process.create_time())] = process
                if Path(process.exe()).resolve() != self.binary:
                    continue
                args = process.cmdline()
                if 'app-server' not in args:
                    continue
                self.runtimes[(process.pid, process.create_time())] = process
                self.affinities[str(process.pid)] = process.cpu_affinity()
                for arg in args:
                    if arg.startswith('mcp_servers='):
                        url = urlparse(tomllib.loads(arg)['mcp_servers']['inspectorpro']['url'])
                        if url.hostname != '127.0.0.1' or not url.port:
                            raise RuntimeError('Test runtime is not using its loopback MCP server')
                        self.ports.add(url.port)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

    def live_runtimes(self):
        return [process for process in self.runtimes.values() if alive(process)]

    def open_ports(self):
        result = []
        for port in self.ports:
            with socket.socket() as sock:
                sock.settimeout(0.1)
                if sock.connect_ex(('127.0.0.1', port)) == 0:
                    result.append(port)
        return result

    def poll_control(self):
        request_path = self.round_output / 'control-request.json'
        if self.active_control is None and request_path.is_file():
            request = read_json(request_path)
            if request['id'] in self.handled:
                return
            if request['kind'] not in {'disconnect', 'settle-cancel'}:
                raise RuntimeError('Unauthorized test control')
            journal, _, _ = read_audit(self.output)
            row = next((row for row in journal if row['turnId'] == request['turnId']), None)
            if not row:
                raise RuntimeError('Control does not identify an actual test turn')
            receipt = {**request, 'startedAt': time.time()}
            if request['kind'] == 'disconnect':
                targets = self.live_runtimes()
                if row['status'] != 'running' or len(targets) != 1:
                    raise RuntimeError('Disconnect requires exactly one owned active runtime')
                # Process objects retain creation time, guarding against PID reuse.
                receipt['terminatedPid'] = targets[0].pid
                targets[0].kill()
            self.active_control = receipt
        if not self.active_control:
            return
        request = self.active_control
        journal, memory, _ = read_audit(self.output)
        pilot = next(row for row in journal if row['turnId'] == request['turnId'])
        turn = next(row for row in memory if row['turnId'] == request['turnId'])
        expected = ('failed', 'failed') if request['kind'] == 'disconnect' else ('interrupted', 'cancelled')
        statuses = (pilot['status'], turn['status'])
        if statuses == expected and not self.live_runtimes() and not self.open_ports():
            request.update(ok=True, pilotStatus=statuses[0], memoryStatus=statuses[1],
                           runtimeStopped=True, listenerClosed=True,
                           elapsedSeconds=round(time.time() - request['startedAt'], 3))
            self.controls.append(request)
            self.handled.add(request['id'])
            write_json(self.round_output / 'control-result.json', request)
            self.active_control = None
        elif time.time() - request['startedAt'] > 30:
            request.update(ok=False, pilotStatus=statuses[0], memoryStatus=statuses[1],
                           liveRuntimePids=[process.pid for process in self.live_runtimes()],
                           openListenerPorts=self.open_ports())
            self.controls.append(request)
            write_json(self.round_output / 'control-result.json', request)
            raise RuntimeError('Interrupted turn or its resources did not settle within 30 seconds')

    def cleanup(self):
        deadline = time.monotonic() + 10
        # Chromium helpers can finish just after the Electron parent exits.
        # Give every observed child the same bounded grace period as Codex.
        while time.monotonic() < deadline and (
                any(alive(process) for process in self.known.values()) or self.open_ports()):
            time.sleep(0.1)
        remaining = [process for process in self.known.values() if alive(process)]
        result = {'runtimePids': sorted({process.pid for process in self.runtimes.values()}),
                  'runtimeAffinities': self.affinities,
                  'runtimeStopped': not self.live_runtimes(), 'listenersClosed': not self.open_ports(),
                  'orphanPids': [process.pid for process in remaining], 'controls': self.controls,
                  'orphanNames': {str(process.pid): self.process_name(process) for process in remaining}}
        for process in remaining:
            try:
                process.kill()
            except psutil.NoSuchProcess:
                pass
        _, still_alive = psutil.wait_procs(remaining, timeout=5)
        result['remainingAfterCleanup'] = [process.pid for process in still_alive]
        result['cleanupConfirmed'] = bool(self.runtimes) and not remaining and result['runtimeStopped'] and result['listenersClosed']
        return result

    @staticmethod
    def process_name(process):
        try:
            return process.name()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return 'unavailable'


@contextmanager
def affinity_scope(count):
    process = psutil.Process()
    original = process.cpu_affinity()
    selected = original[:count] if count else original
    if count and (count > len(original) or len(original) < 4):
        raise ValueError('Load checks require at least four available CPUs')
    process.cpu_affinity(selected)
    try:
        yield selected
    finally:
        process.cpu_affinity(original)


def load_worker(stop_path):
    started, cpu_started = time.monotonic(), time.process_time()
    cycles = 0
    while not stop_path.exists() and time.monotonic() - started < 600:
        cycle = time.monotonic()
        while time.monotonic() - cycle < 0.09:
            hashlib.sha256(b'bounded-startup-load' * 2048).digest()
        time.sleep(max(0, 0.1 - (time.monotonic() - cycle)))
        cycles += 1
    print(json.dumps({'wallSeconds': time.monotonic() - started,
                      'cpuSeconds': time.process_time() - cpu_started, 'cycles': cycles}))


def run_reliability(command, env, output, binary, scenario, load_workers=0, affinity_cpus=0):
    result = {'status': 'running', 'scenario': scenario, 'startedAt': time.time(),
              'loadWorkers': load_workers, 'rounds': []}
    workers = []
    stop = output / 'stop-load'
    try:
        with affinity_scope(affinity_cpus) as cpus:
            result['affinityCpus'] = cpus
            worker_env = {key: value for key, value in os.environ.items()
                          if key.upper() in {'SYSTEMROOT', 'WINDIR', 'PATH', 'TEMP', 'TMP', 'PYTHONPATH', 'USERPROFILE', 'APPDATA'}}
            for index in range(load_workers):
                log = (output / f'load-{index}.json').open('wb')
                process = subprocess.Popen([sys.executable, __file__, '--load-worker', str(stop)],
                    env=worker_env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, creationflags=FLAGS)
                workers.append((process, log))
            stages = ['before-restart', 'after-restart'] if scenario == 'recovery' else [scenario]
            for stage in stages:
                round_output = output / stage
                round_output.mkdir()
                current_env = {**env, 'INSPECTORPRO_CODEX_DESKTOP_RELIABILITY': stage}
                current = list(command)
                current[current.index('--codex-acceptance-output') + 1] = str(round_output)
                with (round_output / 'stdout.log').open('wb') as stdout, (round_output / 'stderr.log').open('wb') as stderr:
                    child = subprocess.Popen(current, cwd=Path(__file__).resolve().parents[1], env=current_env,
                        stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, creationflags=FLAGS)
                    monitor = OwnedRuntimeMonitor(child, binary, output, round_output)
                    deadline = time.monotonic() + 600
                    supervision_error = None
                    try:
                        while child.poll() is None:
                            monitor.observe()
                            monitor.poll_control()
                            if time.monotonic() > deadline:
                                raise TimeoutError('Native reliability round exceeded 600 seconds')
                            time.sleep(0.1)
                    except Exception as error:
                        supervision_error = type(error).__name__ + ': ' + str(error)
                        child.kill()
                    finally:
                        child.wait(timeout=15)
                        ownership = monitor.cleanup()
                ui = read_json(round_output / 'codex-ui-check.json') if (round_output / 'codex-ui-check.json').is_file() else {}
                runtime = read_json(output / 'last-application-run.json') if (output / 'last-application-run.json').is_file() else {}
                write_json(round_output / 'desktop-cleanup.json', runtime)
                round_result = {'stage': stage, 'exitCode': child.returncode, 'ownership': ownership,
                                'ui': ui, 'desktop': runtime, 'supervisionError': supervision_error}
                result['rounds'].append(round_result)
                cleanups = [row.get('cleanup') or {} for row in runtime.get('backends', [])]
                if not (child.returncode == 0 and not supervision_error and ui.get('status') == 'passed'
                        and ownership['cleanupConfirmed'] and cleanups
                        and all(clean_desktop_shutdown(row) for row in cleanups)):
                    raise RuntimeError('Native round failed; retained UI and process evidence')
        journal, memory, sessions = read_audit(output)
        result.update(journal=journal, memory=memory, sessionCount=sessions)
        turns = [turn for row in result['rounds'] for turn in row['ui']['turns']]
        expected = (['completed', 'interrupted', 'completed', 'failed', 'completed'] if scenario == 'recovery'
                    else ['interrupted'] if scenario == 'editor-change' else ['completed'])
        expected_memory = (['committed', 'cancelled', 'committed', 'failed', 'committed'] if scenario == 'recovery'
                           else ['cancelled'] if scenario == 'editor-change' else ['committed'])
        assert [row['status'] for row in journal] == expected
        assert [row['status'] for row in memory] == expected_memory
        assert len(turns) == len(expected) and len({turn['turnId'] for turn in turns}) == len(turns)
        assert len({turn['conversationId'] for turn in turns}) == len({turn['agentSessionId'] for turn in turns}) == sessions == 1
        assert all(row['hasManifest'] and row['model'].get('runtime') == 'codex_app_server'
                   and row['model'].get('model') == 'gpt-5.5' for row in memory if row['status'] == 'committed')
        assert all(row['ui']['sourceUnchanged'] and row['ui']['saveCalls'] == 0
                   and (row['ui'].get('copyRestored') if scenario in {'editing', 'authoring'} else row['ui']['copyUnchanged'])
                   for row in result['rounds'])
        if scenario == 'recovery':
            assert result['rounds'][1]['ui']['restartRestoredConversation'] is True
            for index in (2, 4):
                timeline = turns[index]['terminal']['final']['codex_inspection']['runtimeTimeline']
                assert any(row['phase'] == 'thread/resume:done' for row in timeline)
            assert journal[3]['result']['code'] == 'codex_runtime_stopped'
        result['status'] = 'passed'
    except Exception as error:
        result.update(status='failed', error=type(error).__name__ + ': ' + str(error))
    finally:
        stop.touch()
        for process, log in workers:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
                result.update(status='failed', loadCleanupForced=True)
            log.close()
        result['loadResults'] = []
        for index, (process, _) in enumerate(workers):
            try:
                metrics = read_json(output / f'load-{index}.json')
                result['loadResults'].append(metrics)
                if process.returncode != 0 or metrics['cpuSeconds'] < 0.15 * metrics['wallSeconds']:
                    result.update(status='failed', insufficientLoad=True)
            except (OSError, ValueError, KeyError):
                result.update(status='failed', loadMetricsMissing=True)
        result['loadStopped'] = all(process.poll() is not None for process, _ in workers)
        result['elapsedSeconds'] = round(time.time() - result['startedAt'], 3)
        write_json(output / 'reliability.json', result)
    return result


if __name__ == '__main__':
    if len(sys.argv) != 3 or sys.argv[1] != '--load-worker':
        raise SystemExit('This helper is only invoked by the isolated native test launcher')
    load_worker(Path(sys.argv[2]))
