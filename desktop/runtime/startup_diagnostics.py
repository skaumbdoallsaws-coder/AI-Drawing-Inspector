"""Opt-in bounded import stacks. Never prints frame locals, source, or argv."""
from __future__ import annotations
import faulthandler
import json
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from desktop.runtime.profile import local_path


class StartupImportDiagnostics:
    def __init__(self, timeout_seconds=30, *, handler=faulthandler, stderr=None):
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (float, int)) or not 0 < timeout_seconds <= 30:
            raise ValueError('Stack watchdog must be positive and no longer than 30 seconds')
        self.timeout = timeout_seconds
        self.handler = handler
        self.stderr = stderr if stderr is not None else sys.stderr
        self.stream = None
        self.started = False
        self.stopped = False
        self.bound = False
        self.shutdown_captured = False
        self.lock = threading.Lock()

    def start(self):
        with self.lock:
            if self.started or self.stopped: raise RuntimeError('Import diagnostic already started or stopped')
            # C watchdog can report a thread blocked while importing an extension.
            # A single timed dump bounds output even if its parent disappears.
            self.started = True
            self.handler.dump_traceback_later(self.timeout, repeat=False, file=self.stderr, exit=False)

    def bind(self, data_root, instance_id, process_id):
        if str(uuid.UUID(instance_id)) != instance_id or type(process_id) is not int or process_id < 1:
            raise ValueError('Owned diagnostic identity required')
        with self.lock:
            if not self.started or self.stopped or self.bound: raise RuntimeError('Diagnostic cannot bind this lifecycle')
            data_root = local_path(Path(data_root))
            directory = local_path(data_root / 'desktop-logs')
            directory.mkdir(exist_ok=True)
            stack_path = local_path(directory / (instance_id + '-import-stacks.log'))
            metadata_path = local_path(directory / (instance_id + '-import-diagnostics.json'))
            # Exclusive files keep previous failed evidence intact.
            stream = stack_path.open('xb', buffering=0)
            try:
                metadata = {'schemaVersion': 1, 'instanceId': instance_id, 'processId': process_id,
                    'mode': 'cpython-importtime-with-bounded-stacks', 'stackFile': stack_path.name,
                    'stackTimeoutSeconds': self.timeout, 'repeat': False, 'exit': False,
                    'pythonExecutable': sys.executable, 'pythonVersion': sys.version.split()[0],
                    'workingDirectory': os.getcwd(), 'importTimeEnabled': bool(sys._xoptions.get('importtime')),
                    'startedUnixMs': int(time.time() * 1000), 'recordsLocals': False, 'recordsArguments': False}
                with metadata_path.open('x', encoding='utf-8') as output:
                    json.dump(metadata, output, separators=(',', ':')); output.write('\n'); output.flush(); os.fsync(output.fileno())
                # Never close/reuse a descriptor until its C watchdog is cancelled.
                self.handler.cancel_dump_traceback_later()
                self.stream = stream
                stream.write(b'InspectorPro import stack baseline (no locals or source)\n')
                self.handler.dump_traceback(file=stream, all_threads=True)
                self.handler.dump_traceback_later(self.timeout, repeat=False, file=stream, exit=False)
                self.bound = True
            except BaseException:
                # If cancellation itself fails, retain the descriptor until a
                # later stop or process exit; the watchdog may still own it.
                self.stream = stream
                try:
                    self.handler.cancel_dump_traceback_later()
                except Exception:
                    raise
                else:
                    self.stream = None
                    stream.close()
                raise

    def capture_shutdown(self):
        with self.lock:
            if not self.started or self.stopped or self.shutdown_captured: return
            self.shutdown_captured = True
            output = self.stream if self.stream is not None else self.stderr
            if self.stream is not None:
                self.stream.write(('\nInspectorPro shutdown-request stack at Unix ms ' + str(int(time.time() * 1000)) + '\n').encode('ascii'))
            self.handler.dump_traceback(file=output, all_threads=True)

    def stop(self):
        with self.lock:
            if self.stopped: return
            if self.started: self.handler.cancel_dump_traceback_later()
            if self.stream is not None:
                self.stream.close()
                self.stream = None
            self.stopped = True
