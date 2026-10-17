"""Opt-in bounded import stacks. Never prints frame locals, source, or argv."""
from __future__ import annotations
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
import uuid
from desktop.runtime.profile import local_path


class CooperativeTracebackHandler:
    """Sample retained Python frames, avoiding CPython's asynchronous C watchdog.

    Requires interpreter progress; a GIL-holding native stall is still bounded
    by the parent's startup deadline, not by this diagnostic thread.
    """
    def __init__(self, max_dumps=6):
        if type(max_dumps) is not int or not 1 <= max_dumps <= 1024:
            raise ValueError('Diagnostic dump count must be bounded')
        self.max_dumps = max_dumps
        self._cancel = None
        self._thread = None
        self._write_lock = threading.Lock()

    @staticmethod
    def _write(file, text):
        encoded = text.encode('ascii', errors='backslashreplace')
        try: file.write(encoded.decode('ascii'))
        except TypeError: file.write(encoded)
        file.flush()

    def dump_traceback(self, *, file, all_threads=True):
        with self._write_lock:
            frames = sys._current_frames()
            try:
                identities = sorted(frames)[:100] if all_threads else [threading.get_ident()]
                output = []
                for identity in identities:
                    output.append(f'Thread 0x{identity:x} (most recent call first):\n')
                    frame = frames.get(identity)
                    count = 0
                    while frame is not None and count < 100:
                        code = frame.f_code
                        # Never fetch source lines, locals, arguments, or reprs.
                        filename = json.dumps(code.co_filename[:500], ensure_ascii=True)
                        name = json.dumps(code.co_name[:500], ensure_ascii=True)[1:-1]
                        output.append(f'  File {filename}, line {frame.f_lineno} in {name}\n')
                        frame = frame.f_back
                        count += 1
                    if frame is not None: output.append('  [frames truncated]\n')
                    output.append('\n')
                if all_threads and len(frames) > 100: output.append('[threads truncated]\n')
                self._write(file, ''.join(output))
            finally:
                frames.clear()

    def dump_traceback_later(self, timeout, *, repeat=False, file, exit=False):
        if (isinstance(timeout, bool) or not isinstance(timeout, (int, float))
                or not math.isfinite(timeout) or timeout <= 0 or exit is not False):
            raise ValueError('Diagnostic requires a finite positive interval and cannot exit the process')
        self.cancel_dump_traceback_later()
        cancel = threading.Event()
        def sample():
            for _ in range(self.max_dumps if repeat else 1):
                if cancel.wait(timeout): return
                try:
                    with self._write_lock:
                        self._write(file, f'Timeout ({timeout:g}s); cooperative Python stack sample\n')
                    self.dump_traceback(file=file, all_threads=True)
                except Exception:
                    # Diagnostics cannot replace the primary import failure.
                    return
        self._cancel = cancel
        self._thread = threading.Thread(target=sample, name='desktop-import-diagnostic', daemon=True)
        self._thread.start()

    def cancel_dump_traceback_later(self):
        if self._cancel is None: return
        self._cancel.set()
        if self._thread is not threading.current_thread(): self._thread.join(timeout=1)
        if self._thread.is_alive():
            raise RuntimeError('Diagnostic writer has not stopped; retain its output descriptor')
        self._cancel = self._thread = None


class StartupImportDiagnostics:
    def __init__(self, timeout_seconds=30, *, handler=None, stderr=None):
        if isinstance(timeout_seconds, bool) or not isinstance(timeout_seconds, (float, int)) or not 0 < timeout_seconds <= 30:
            raise ValueError('Stack watchdog must be positive and no longer than 30 seconds')
        self.timeout = timeout_seconds
        self.handler = handler if handler is not None else CooperativeTracebackHandler()
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
            # A single cooperative sample bounds output if its parent disappears.
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
                    'stackSampler': 'cooperative-python-frames', 'requiresInterpreterProgress': True,
                    'startedUnixMs': int(time.time() * 1000), 'recordsLocals': False, 'recordsArguments': False}
                with metadata_path.open('x', encoding='utf-8') as output:
                    json.dump(metadata, output, separators=(',', ':')); output.write('\n'); output.flush(); os.fsync(output.fileno())
                # Never close/reuse a descriptor until its sampler is cancelled.
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
