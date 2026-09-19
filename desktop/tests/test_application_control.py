import json
import os
import subprocess
import sys
import threading
import time
import unittest
import uuid
from desktop.runtime.control_pipe import NonBlockingControlPipe
from desktop.runtime.managed_backend import bootstrap, PrivateControl


class ApplicationControlTests(unittest.TestCase):
    def setUp(self):
        self.reader, self.writer = os.pipe()
        self.addCleanup(os.close, self.reader)
        self.addCleanup(os.close, self.writer)
        self.pipe = NonBlockingControlPipe(self.reader)

    def test_bootstrap_and_early_shutdown_in_one_write_are_both_consumed(self):
        request = str(uuid.uuid4())
        data = {'schemaVersion': 1, 'credential': 'a' * 64, 'instanceId': str(uuid.uuid4())}
        shutdown = {'schemaVersion': 1, 'command': 'shutdown', 'requestId': request}
        os.write(self.writer, (json.dumps(data) + '\n' + json.dumps(shutdown) + '\n').encode())
        self.assertEqual(bootstrap(self.pipe), data)
        control = PrivateControl(self.pipe)
        control.read()
        self.assertTrue(control.stop.is_set())
        self.assertFalse(control.invalid)
        self.assertEqual(control.request_id, request)

    def test_fragmented_line_and_limit(self):
        def write():
            for chunk in [b'ab', b'cd', b'\nnext\n']:
                os.write(self.writer, chunk)
                time.sleep(0.01)
        t = threading.Thread(target=write)
        t.start()
        self.assertEqual(self.pipe.readline(4097), b'abcd\n')
        self.assertEqual(self.pipe.readline(4097), b'next\n')
        t.join()
        os.write(self.writer, b'x' * 10)
        self.assertEqual(self.pipe.readline(6), b'x' * 6)

    def test_invalid_control_stays_invalid(self):
        os.write(self.writer, b'{"command":"save"}\n')
        control = PrivateControl(self.pipe)
        control.read()
        self.assertTrue(control.invalid)
        self.assertIsNone(control.request_id)

    def test_idle_control_does_not_stall_native_numpy_import(self):
        code = """import sys,threading,json,time
from desktop.runtime.control_pipe import NonBlockingControlPipe
p=NonBlockingControlPipe(0)
t=threading.Thread(target=lambda:p.readline(4097));t.start()
started=time.perf_counter()
import numpy
print('imported',flush=True)
t.join(5)
"""
        process = subprocess.Popen([sys.executable, '-u', '-c', code], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        try:
            # Leave the control channel open during import, then close it.
            observed = []
            reader = threading.Thread(target=lambda: observed.append(process.stdout.readline()))
            reader.start(); reader.join(8)
            self.assertFalse(reader.is_alive(), 'Native import stalled on an idle control pipe')
            self.assertEqual(observed, [b'imported\r\n' if os.name == 'nt' else b'imported\n'])
            process.stdin.close()
            self.assertEqual(process.wait(timeout=8), 0)
        finally:
            if process.poll() is None: process.kill(); process.wait(timeout=8)
            process.stdout.close(); process.stderr.close()


if __name__ == '__main__': unittest.main()
