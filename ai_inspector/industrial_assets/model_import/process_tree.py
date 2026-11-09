"""Host-side lifetime containment in addition to the worker's resource limits.

Windows venv launchers can create an interpreter child. Use the base executable
and a kill-on-close Job Object; POSIX workers own a fresh process group.
"""
import os
from pathlib import Path
import signal
import sys
import time

from .errors import ModelImportError


def base_executable() -> str:
    value = getattr(sys, "_base_executable", sys.executable)
    try:
        path = Path(value)
        if not path.is_absolute() or not path.is_file():
            raise ValueError()
        return str(path)
    except (OSError, TypeError, ValueError):
        raise ModelImportError("model_runtime_unavailable") from None


class ProcessTree:
    """Create the Windows job before Popen, then attach immediately after spawn."""

    def __init__(self):
        self.handle = None
        if os.name != "nt":
            return
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                        ("processes", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(key, ctypes.c_uint64) for key in ("a", "b", "c", "d", "e", "f")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]

        class Accounting(ctypes.Structure):
            _fields_ = [(key, ctypes.c_int64) for key in ("user", "kernel", "period_user", "period_kernel")]
            _fields_ += [(key, wintypes.DWORD) for key in ("faults", "total", "active", "terminated")]

        self.ctypes, self.Accounting = ctypes, Accounting
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.TerminateJobObject.argtypes = (wintypes.HANDLE, wintypes.UINT)
        kernel.TerminateJobObject.restype = wintypes.BOOL
        kernel.QueryInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                     wintypes.DWORD, ctypes.c_void_p)
        kernel.QueryInformationJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.CloseHandle.restype = wintypes.BOOL
        self.kernel = kernel
        handle = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2000  # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE, no competing CPU/memory limits.
        if not handle or not kernel.SetInformationJobObject(handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            if handle:
                kernel.CloseHandle(handle)
            raise ModelImportError("model_limits_unavailable")
        self.handle = handle

    def attach(self, process) -> None:
        if self.handle is not None and not self.kernel.AssignProcessToJobObject(self.handle, int(process._handle)):
            raise ModelImportError("model_limits_unavailable")

    def stop(self, process) -> None:
        """Terminate the entire owned tree, wait for the leader, then close the job."""
        try:
            if self.handle is not None:
                self.kernel.TerminateJobObject(self.handle, 1)
                # Wait for child handles/cwd references as well as the leader.
                deadline = time.monotonic() + 2
                while time.monotonic() < deadline:
                    info = self.Accounting()
                    if (not self.kernel.QueryInformationJobObject(self.handle, 1, self.ctypes.byref(info),
                                                                  self.ctypes.sizeof(info), None) or not info.active):
                        break
                    time.sleep(.02)
            elif os.name != "nt":
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
        finally:
            # Closing the Windows job also kills its members if TerminateJobObject failed.
            self.close()
            if process.poll() is None:
                process.kill()
            process.wait()
            if os.name == "nt":
                process._handle.Close()

    def close(self) -> None:
        if self.handle is not None:
            self.kernel.CloseHandle(self.handle)
            self.handle = None
