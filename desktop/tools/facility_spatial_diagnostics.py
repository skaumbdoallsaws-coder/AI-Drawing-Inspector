"""Observational spatial-job timing for the explicit managed recovery fixture."""
import json
import os
import re
import sys
import threading
import time

PREFIX = 'INSPECTORPRO_FACILITY_SPATIAL_JOB '


def install_spatial_diagnostics(executor, *, emit=None):
    """Keep the actual pool, job object, cancellation, result and deadline intact."""
    if os.environ.get('INSPECTORPRO_FACILITY_MANAGED_RESTART_HARNESS') != '1':
        raise ValueError('Explicit managed recovery harness required for spatial diagnostics')
    if getattr(executor, '_managed_spatial_diagnostics_installed', False):
        return
    original_submit = executor._submit
    output_lock = threading.Lock()
    sequence_lock = threading.Lock()
    sequence = 0

    def write(record):
        try:
            # Logging has no access to arguments, document contents or credentials.
            with output_lock:
                if emit is not None:
                    emit(dict(record))
                else:
                    sys.stderr.write(PREFIX + json.dumps(record, separators=(',', ':')) + '\n')
                    sys.stderr.flush()
        except Exception:
            pass

    def submit(operation, args, kwargs):
        nonlocal sequence
        with sequence_lock:
            sequence += 1
            observation_id = sequence
        submitted = time.monotonic()
        timing_lock = threading.Lock()
        timing = {}
        context = {'schemaVersion': 1, 'pid': os.getpid(), 'observationId': observation_id,
                   'operation': 'diagnostics' if operation is executor._diagnose else 'candidates',
                   'configuredTimeoutSeconds': executor._timeout_seconds}
        instance = os.environ.get('INSPECTORPRO_DESKTOP_INSTANCE_ID', '')
        if re.fullmatch(r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', instance):
            context['instanceId'] = instance.lower()

        def observed_operation(*values, **options):
            wall, cpu = time.monotonic(), time.thread_time()
            with timing_lock:
                timing['started'] = wall
            try:
                return operation(*values, **options)
            finally:
                with timing_lock:
                    timing.update(ended=time.monotonic(), threadCpuMs=(time.thread_time() - cpu) * 1000)

        job = original_submit(observed_operation, args, kwargs)
        context['jobId'] = job.job_id
        write({**context, 'event': 'submitted', 'timeUnixMs': int(time.time() * 1000)})

        def finished(future):
            try:
                with timing_lock:
                    measured = dict(timing)
                started, ended = measured.get('started'), measured.get('ended')
                cancelled = future.cancelled() or job.token.cancelled
                failure = None if future.cancelled() else future.exception()
                record = {**context, 'event': 'settled', 'timeUnixMs': int(time.time() * 1000),
                          'status': 'cancelled' if cancelled else 'failed' if failure else 'completed',
                          'started': started is not None, 'cancellationRequested': job.token.cancelled,
                          'totalMs': max(0, (time.monotonic() - submitted) * 1000),
                          'queueMs': None if started is None else max(0, (started - submitted) * 1000),
                          'executionMs': None if started is None or ended is None else max(0, (ended - started) * 1000),
                          'threadCpuMs': measured.get('threadCpuMs')}
                code = getattr(failure, 'code', None)
                if isinstance(code, str) and re.fullmatch(r'[a-z][a-z0-9_]{0,127}', code):
                    record['errorCode'] = code
                write(record)
            except Exception:
                pass

        job.future.add_done_callback(finished)
        return job

    executor._submit = submit
    executor._managed_spatial_diagnostics_installed = True
