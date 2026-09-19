"""Managed-harness instrumentation preserves the real bounded spatial executor."""
from concurrent.futures import Future
import importlib.util
import io
import json
from pathlib import Path
import threading
import time

import pytest

from ai_inspector.facility_layout.errors import FacilityValidationError
from ai_inspector.facility_layout.spatial_executor import (
    FacilitySpatialExecutor, SpatialExecutionCancelled, SpatialJob,
)


SCRIPT = Path(__file__).resolve().parents[1] / 'tools' / 'facility_spatial_diagnostics.py'
spec = importlib.util.spec_from_file_location('facility_spatial_diagnostics_test', SCRIPT)
observer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(observer)
INSTANCE = '18d6cd63-07c9-4fb1-ad2a-6835c7342ed9'


class Events:
    def __init__(self):
        self.values = []
        self.changed = threading.Condition()

    def emit(self, value):
        with self.changed:
            self.values.append(dict(value))
            self.changed.notify_all()

    def settled(self, count=1):
        with self.changed:
            assert self.changed.wait_for(
                lambda: sum(value['event'] == 'settled' for value in self.values) >= count, timeout=2
            ), 'Real executor did not deliver settlement diagnostics'
            return [value for value in self.values if value['event'] == 'settled']


@pytest.fixture
def managed_environment(monkeypatch):
    monkeypatch.setenv('INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS', '1')
    monkeypatch.setenv('INSPECTORPRO_DESKTOP_INSTANCE_ID', INSTANCE)


def captured_jobs(executor):
    submitted = []
    original = executor._submit

    def capture(*args, **kwargs):
        job = original(*args, **kwargs)
        submitted.append(job)
        return job

    executor._submit = capture
    return submitted


def test_import_is_silent_even_when_managed_environment_is_set(managed_environment, monkeypatch):
    output = io.StringIO()
    monkeypatch.setattr(observer.sys, 'stderr', output)
    fresh_spec = importlib.util.spec_from_file_location('facility_spatial_diagnostics_import', SCRIPT)
    fresh = importlib.util.module_from_spec(fresh_spec)
    fresh_spec.loader.exec_module(fresh)
    assert output.getvalue() == ''


def test_install_requires_managed_harness_and_does_not_change_rejected_executor(monkeypatch):
    monkeypatch.delenv('INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS', raising=False)
    executor = FacilitySpatialExecutor()
    original = executor._submit
    try:
        with pytest.raises(ValueError, match='Explicit managed'):
            observer.install_spatial_diagnostics(executor)
        assert executor._submit == original
        assert not getattr(executor, '_managed_spatial_diagnostics_installed', False)
        assert executor._timeout_seconds == 5.0
    finally:
        executor.close()


def test_success_preserves_exact_arguments_result_real_job_pool_and_default_deadline(managed_environment):
    layout, definitions = {'secretPayload': 'document-never-log'}, {'secretAsset': 'asset-never-log'}
    result = {'valid': True, 'nested': {'identity': object()}}
    received = []

    def diagnose(*args, cancel_check, **kwargs):
        cancel_check()
        received.append((args, kwargs))
        return result

    executor = FacilitySpatialExecutor(diagnose=diagnose)
    pool, pending = executor._pool, executor._pending
    submitted, events = captured_jobs(executor), Events()
    try:
        observer.install_spatial_diagnostics(executor, emit=events.emit)
        job = executor.submit_diagnostics(layout, definitions, marker='credential-never-log')
        assert job is submitted[0]
        assert type(job) is SpatialJob
        assert isinstance(job.future, Future)
        assert job.result(timeout=2) is result
        assert received[0][0][0] is layout
        assert received[0][0][1] is definitions
        assert received[0][1] == {'marker': 'credential-never-log'}
        assert executor._pool is pool and executor._pending is pending
        assert executor._timeout_seconds == 5.0
        final = events.settled()[0]
        assert [event['event'] for event in events.values] == ['submitted', 'settled']
        assert {event['jobId'] for event in events.values} == {job.job_id}
        assert {event['configuredTimeoutSeconds'] for event in events.values} == {5.0}
        assert {event['instanceId'] for event in events.values} == {INSTANCE}
        assert final['status'] == 'completed' and final['started'] is True
        assert final['cancellationRequested'] is False
        assert final['queueMs'] >= 0 and final['executionMs'] >= 0 and final['threadCpuMs'] >= 0
        assert final['totalMs'] >= final['queueMs']
        serialized = json.dumps(events.values)
        for secret in ('document-never-log', 'asset-never-log', 'credential-never-log', 'secretPayload'):
            assert secret not in serialized
    finally:
        executor.close()


def test_queue_time_is_measured_with_the_existing_single_worker_and_capacity(managed_environment):
    first_started, release, second_started = threading.Event(), threading.Event(), threading.Event()

    def diagnose(layout, _definitions, cancel_check):
        if layout['order'] == 1:
            first_started.set()
            while not release.wait(0.002):
                cancel_check()
        else:
            second_started.set()
        return layout

    executor = FacilitySpatialExecutor(maximum_workers=1, maximum_pending_jobs=2, diagnose=diagnose)
    events = Events()
    try:
        observer.install_spatial_diagnostics(executor, emit=events.emit)
        first = executor.submit_diagnostics({'order': 1}, {})
        assert first_started.wait(2)
        second = executor.submit_diagnostics({'order': 2}, {})
        assert not second_started.wait(0.025)
        with pytest.raises(FacilityValidationError) as overloaded:
            executor.submit_diagnostics({'order': 3}, {})
        assert overloaded.value.code == 'spatial_execution_overloaded'
        release.set()
        assert first.result(timeout=2) == {'order': 1}
        assert second.result(timeout=2) == {'order': 2}
        final = {event['jobId']: event for event in events.settled(2)}
        assert set(final) == {first.job_id, second.job_id}
        assert final[second.job_id]['queueMs'] >= 20
        assert final[second.job_id]['status'] == 'completed'
        assert final[first.job_id]['status'] == 'completed'
        assert len(events.values) == 4
    finally:
        release.set()
        executor.close()


def test_timeout_remains_typed_and_cancels_the_same_real_job(managed_environment):
    operation_exited = threading.Event()

    def diagnose(*_args, cancel_check, **_kwargs):
        try:
            while True:
                cancel_check()
                time.sleep(0.001)
        finally:
            operation_exited.set()

    executor = FacilitySpatialExecutor(maximum_workers=1, maximum_pending_jobs=1,
                                       timeout_seconds=0.01, diagnose=diagnose)
    submitted, events = captured_jobs(executor), Events()
    try:
        observer.install_spatial_diagnostics(executor, emit=events.emit)
        with pytest.raises(FacilityValidationError) as raised:
            executor.run_diagnostics({}, {})
        assert raised.value.code == 'spatial_execution_timeout'
        assert executor._timeout_seconds == 0.01
        assert len(submitted) == 1 and type(submitted[0]) is SpatialJob
        assert raised.value.details['jobId'] == submitted[0].job_id
        assert submitted[0].token.cancelled
        assert operation_exited.wait(2)
        final = events.settled()[0]
        assert final['jobId'] == submitted[0].job_id
        assert final['status'] == 'cancelled' and final['cancellationRequested'] is True
        assert final['configuredTimeoutSeconds'] == 0.01
        assert final['errorCode'] == 'spatial_execution_cancelled'
    finally:
        executor.close()


def test_cancelled_queued_job_is_not_started_and_keeps_original_cancel_semantics(managed_environment):
    first_started, release = threading.Event(), threading.Event()
    calls = []

    def diagnose(layout, _definitions, cancel_check):
        calls.append(layout['order'])
        first_started.set()
        while not release.wait(0.002):
            cancel_check()
        return {'valid': True}

    executor = FacilitySpatialExecutor(maximum_workers=1, maximum_pending_jobs=2, diagnose=diagnose)
    events = Events()
    try:
        observer.install_spatial_diagnostics(executor, emit=events.emit)
        first = executor.submit_diagnostics({'order': 1}, {})
        assert first_started.wait(2)
        queued = executor.submit_diagnostics({'order': 2}, {})
        assert queued.cancel() is True
        with pytest.raises(SpatialExecutionCancelled):
            queued.result(timeout=2)
        final = events.settled()[0]
        assert final['jobId'] == queued.job_id and final['status'] == 'cancelled'
        assert final['started'] is False and final['cancellationRequested'] is True
        assert final['queueMs'] is None and final['executionMs'] is None and final['threadCpuMs'] is None
        assert calls == [1]
        release.set()
        assert first.result(timeout=2) == {'valid': True}
        events.settled(2)
    finally:
        release.set()
        executor.close()


def test_failure_preserves_error_identity_and_emits_only_typed_code(managed_environment, monkeypatch):
    monkeypatch.setenv('OPENAI_API_KEY', 'credential-not-for-diagnostics')
    failure = FacilityValidationError('spatial_controlled_failure', 'error-message-not-for-diagnostics',
                                      details={'document': 'private-error-detail'})

    def diagnose(*_args, **_kwargs):
        raise failure

    executor = FacilitySpatialExecutor(diagnose=diagnose)
    events = Events()
    try:
        observer.install_spatial_diagnostics(executor, emit=events.emit)
        job = executor.submit_diagnostics({'private-payload': 'private-layout'}, {})
        with pytest.raises(FacilityValidationError) as raised:
            job.result(timeout=2)
        assert raised.value is failure
        final = events.settled()[0]
        assert final['status'] == 'failed' and final['errorCode'] == failure.code
        assert final['jobId'] == job.job_id
        serialized = json.dumps(events.values)
        for secret in ('credential-not-for-diagnostics', 'error-message-not-for-diagnostics',
                       'private-error-detail', 'private-payload', 'private-layout'):
            assert secret not in serialized
        assert 'message' not in final and 'stack' not in final and 'details' not in final
    finally:
        executor.close()


def test_invalid_instance_and_message_like_error_code_are_not_logged(managed_environment, monkeypatch):
    monkeypatch.setenv('INSPECTORPRO_DESKTOP_INSTANCE_ID', 'invalid-instance-private-token')
    failure = RuntimeError('private-error-message')
    failure.code = 'bad code: private-credential'

    def diagnose(*_args, **_kwargs):
        raise failure

    executor = FacilitySpatialExecutor(diagnose=diagnose)
    events = Events()
    try:
        observer.install_spatial_diagnostics(executor, emit=events.emit)
        with pytest.raises(RuntimeError) as raised:
            executor.run_diagnostics({}, {})
        assert raised.value is failure
        final = events.settled()[0]
        assert 'errorCode' not in final
        assert all('instanceId' not in event for event in events.values)
        serialized = json.dumps(events.values)
        assert 'private-token' not in serialized and 'private-credential' not in serialized
        assert 'private-error-message' not in serialized
    finally:
        executor.close()


def test_emitter_failure_never_changes_success_or_original_failure(managed_environment):
    result = {'valid': True}
    failure = RuntimeError('real operation failure')

    def diagnose(layout, _definitions, **_kwargs):
        if layout.get('fail'):
            raise failure
        return result

    def broken_emit(_record):
        raise OSError('controlled diagnostic sink failure')

    executor = FacilitySpatialExecutor(diagnose=diagnose)
    try:
        observer.install_spatial_diagnostics(executor, emit=broken_emit)
        assert executor.run_diagnostics({}, {}) is result
        with pytest.raises(RuntimeError) as raised:
            executor.run_diagnostics({'fail': True}, {})
        assert raised.value is failure
        assert executor.run_diagnostics({}, {}) is result
        assert executor._timeout_seconds == 5.0
    finally:
        executor.close()


def test_repeat_installation_does_not_wrap_again_or_duplicate_events(managed_environment):
    executor = FacilitySpatialExecutor(diagnose=lambda *_args, **_kwargs: {'valid': True})
    events = Events()
    try:
        observer.install_spatial_diagnostics(executor, emit=events.emit)
        installed = executor._submit
        observer.install_spatial_diagnostics(executor, emit=lambda _value: pytest.fail('Second sink must not be installed'))
        assert executor._submit is installed
        assert executor.run_diagnostics({}, {}) == {'valid': True}
        events.settled()
        assert len(events.values) == 2
    finally:
        executor.close()
