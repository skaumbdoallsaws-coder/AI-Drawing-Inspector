"""Test-driver guards only; no inference or real process termination."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools import codex_desktop_reliability as reliability


@pytest.mark.parametrize('change', [{}, {'forced': True}, {'forced': None}, {'exitCode': None},
                                  {'exitCode': 1}, {'resourcesClosed': False}, {'stdioClosed': False}])
def test_native_acceptance_requires_clean_zero_exit(change):
    receipt = {'forced': False, 'exitCode': 0, 'terminationConfirmed': True,
               'stdioClosed': True, 'resourcesClosed': True}
    receipt.update(change)
    assert reliability.clean_desktop_shutdown(receipt) is (not change)


def monitor(tmp_path, monkeypatch, status='running', kind='disconnect'):
    value = reliability.OwnedRuntimeMonitor.__new__(reliability.OwnedRuntimeMonitor)
    value.output = value.round_output = tmp_path
    value.handled, value.controls, value.active_control = set(), [], None
    process = SimpleNamespace(pid=123, kills=0)
    def kill():
        process.kills += 1
    process.kill = kill
    value.live_runtimes = lambda: [process] if not process.kills else []
    value.open_ports = lambda: []
    monkeypatch.setattr(reliability, 'read_audit', lambda _: (
        [{'turnId': 'owned-turn', 'status': 'failed' if process.kills else status}],
        [{'turnId': 'owned-turn', 'status': 'failed' if process.kills else 'pending'}], 1))
    reliability.write_json(tmp_path / 'control-request.json', {'id': 'request-1', 'turnId': 'owned-turn', 'kind': kind})
    return value, process


def test_disconnect_only_occurs_once_after_owned_active_turn_check(tmp_path, monkeypatch):
    value, process = monitor(tmp_path, monkeypatch)
    value.poll_control()
    value.poll_control()
    assert process.kills == 1
    receipt = reliability.read_json(tmp_path / 'control-result.json')
    assert receipt['ok'] and receipt['listenerClosed'] and receipt['runtimeStopped']
    assert receipt['memoryStatus'] == receipt['pilotStatus'] == 'failed'


@pytest.mark.parametrize('status,kind', [('completed', 'disconnect'), ('running', 'arbitrary-kill')])
def test_invalid_controls_cannot_terminate_processes(tmp_path, monkeypatch, status, kind):
    value, process = monitor(tmp_path, monkeypatch, status, kind)
    with pytest.raises(RuntimeError):
        value.poll_control()
    assert process.kills == 0


def test_unknown_turn_cannot_terminate_processes(tmp_path, monkeypatch):
    value, process = monitor(tmp_path, monkeypatch)
    reliability.write_json(tmp_path / 'control-request.json', {'id': 'request-1', 'turnId': 'not-owned', 'kind': 'disconnect'})
    with pytest.raises(RuntimeError, match='actual test turn'):
        value.poll_control()
    assert process.kills == 0


def test_open_listener_prevents_successful_interrupt_receipt(tmp_path, monkeypatch):
    value, process = monitor(tmp_path, monkeypatch)
    value.open_ports = lambda: [12345]
    value.poll_control()
    assert process.kills == 1
    assert not (tmp_path / 'control-result.json').exists()
    value.active_control['startedAt'] -= 31
    with pytest.raises(RuntimeError, match='resources did not settle'):
        value.poll_control()


def test_affinity_is_restored_even_after_failure(monkeypatch):
    calls = []
    class Process:
        def cpu_affinity(self, cpus=None):
            if cpus is None:
                return list(range(8))
            calls.append(cpus)
    monkeypatch.setattr(reliability.psutil, 'Process', Process)
    with pytest.raises(RuntimeError):
        with reliability.affinity_scope(2) as cpus:
            assert cpus == [0, 1]
            raise RuntimeError('test failure')
    assert calls == [[0, 1], list(range(8))]


def test_load_worker_obeys_stop_without_work(tmp_path, capsys):
    stop = tmp_path / 'stop'
    stop.touch()
    reliability.load_worker(stop)
    assert json.loads(capsys.readouterr().out)['cycles'] == 0


@pytest.mark.parametrize('helper_exits', [True, False])
def test_cleanup_waits_for_all_owned_children_but_does_not_pass_forced_cleanup(monkeypatch, helper_exits):
    value = reliability.OwnedRuntimeMonitor.__new__(reliability.OwnedRuntimeMonitor)
    clock = [0.0]
    killed = []
    helper = SimpleNamespace(pid=456, name=lambda: 'electron.exe', kill=lambda: killed.append(456))
    runtime = SimpleNamespace(pid=123)
    value.known = {(456, 1): helper, (123, 1): runtime}
    value.runtimes, value.affinities, value.controls = {(123, 1): runtime}, {}, []
    value.live_runtimes, value.open_ports = lambda: [], lambda: []
    monkeypatch.setattr(reliability.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(reliability.time, 'sleep', lambda seconds: clock.__setitem__(0, clock[0] + seconds))
    monkeypatch.setattr(reliability, 'alive', lambda p: p is helper and (not helper_exits or clock[0] < 0.5))
    monkeypatch.setattr(reliability.psutil, 'wait_procs', lambda processes, timeout: (processes, []))
    result = value.cleanup()
    assert result['cleanupConfirmed'] is helper_exits
    assert result['remainingAfterCleanup'] == []
    assert killed == ([] if helper_exits else [456])
    assert clock[0] >= (0.5 if helper_exits else 10)
