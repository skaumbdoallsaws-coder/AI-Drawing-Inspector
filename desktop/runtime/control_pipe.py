"""Bounded line reader that never blocks inside the Windows CRT pipe read.

A concurrent blocking stdin read can stall native extension initialization on
Windows. Polling a nonblocking pipe avoids holding that runtime lock. The wire
protocol and its strict bootstrap/shutdown validation remain unchanged.
"""
import os
import time


class NonBlockingControlPipe:
    def __init__(self, descriptor):
        self.descriptor = descriptor
        self.pending = bytearray()
        self.eof = False
        os.set_blocking(descriptor, False)

    def readline(self, limit):
        if not isinstance(limit, int) or not 1 <= limit <= 4097:
            raise ValueError('Control line limit is invalid')
        while True:
            newline = self.pending.find(b'\n', 0, limit)
            if newline >= 0 or len(self.pending) >= limit or self.eof:
                size = newline + 1 if newline >= 0 else min(limit, len(self.pending))
                line = bytes(self.pending[:size])
                del self.pending[:size]
                return line
            try:
                chunk = os.read(self.descriptor, limit - len(self.pending))
            except BlockingIOError:
                time.sleep(0.025)
                continue
            if chunk: self.pending.extend(chunk)
            else: self.eof = True
