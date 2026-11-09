"""Checked local paths, atomic JSON and process-identity locks for model imports.

The OS-held coordinator lock serializes disk reservations across store instances
and processes. Operation locks are durable leases, never reclaimed by age alone.
"""
from contextlib import contextmanager
import ctypes
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import threading
import time

from .errors import FacilityLayoutError

_LOCAL = threading.RLock()


def safe(path: Path) -> Path:
    path = Path(path).absolute()
    if str(path).startswith(("\\\\", "//")) or ".." in path.parts:
        raise FacilityLayoutError("model_store_invalid", "Model storage must be local.", status_code=503)
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise FacilityLayoutError("model_store_invalid", "Model storage contains a linked path.", status_code=503)
    return path


def mkdir(path: Path) -> Path:
    path = safe(path)
    path.mkdir(parents=True, exist_ok=True)
    return safe(path)


def encode(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def atomic(path: Path, value) -> None:
    path = safe(path)
    mkdir(path.parent)
    fd, temporary = tempfile.mkstemp(prefix=".atomic-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(encode(value))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_json(path: Path, maximum=256 * 1024):
    path = safe(path)
    try:
        if not stat.S_ISREG(path.stat().st_mode):
            return None
        with path.open("rb") as stream:
            data = stream.read(maximum + 1)
        if len(data) > maximum:
            raise ValueError("oversized JSON")
        return json.loads(data)
    except (OSError, ValueError, UnicodeError, RecursionError):
        return None


def size(path: Path) -> int:
    path = safe(path)
    if not path.exists():
        return 0
    if path.is_file():
        return path.stat().st_size
    return sum(size(child) for child in path.iterdir())


def remove(path: Path) -> None:
    from ..industrial_assets.model_import.cleanup import retry_cleanup
    path = safe(path)
    if path.is_dir():
        retry_cleanup(lambda: shutil.rmtree(safe(path)))
    else:
        retry_cleanup(lambda: safe(path).unlink(missing_ok=True))


def process_start(pid: int) -> str | None:
    """None means definitely absent; '?' means unknown and must be treated as live."""
    if type(pid) is not int or pid <= 0:
        return None
    if os.name == "nt":
        from ctypes import wintypes
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
        kernel.OpenProcess.restype = wintypes.HANDLE
        kernel.GetProcessTimes.argtypes = (wintypes.HANDLE,) + (ctypes.POINTER(wintypes.FILETIME),) * 4
        kernel.GetProcessTimes.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        kernel.WaitForSingleObject.argtypes = (wintypes.HANDLE, wintypes.DWORD)
        kernel.WaitForSingleObject.restype = wintypes.DWORD
        handle = kernel.OpenProcess(0x1000 | 0x100000, False, pid)
        if not handle:
            return None if ctypes.get_last_error() == 87 else "?"
        try:
            state = kernel.WaitForSingleObject(handle, 0)
            if state == 0:
                return None  # Exited, even if another process still holds its handle.
            if state != 258:
                return "?"
            times = [wintypes.FILETIME() for _ in range(4)]
            if not kernel.GetProcessTimes(handle, *(ctypes.byref(t) for t in times)):
                return "?"
            return str((times[0].dwHighDateTime << 32) | times[0].dwLowDateTime)
        finally:
            kernel.CloseHandle(handle)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return None
    except PermissionError:
        return "?"
    try:
        proc = Path(f"/proc/{pid}/stat")
        if proc.exists():
            fields = proc.read_text().rsplit(")", 1)[1].split()
            return None if fields[0] == "Z" else fields[19]
        state = subprocess.check_output(["ps", "-p", str(pid), "-o", "stat=", "-o", "lstart="],
                                        timeout=2, text=True).strip().split(None, 1)
        return None if not state or state[0].startswith("Z") else state[1]
    except (OSError, subprocess.SubprocessError):
        return "?"


def owner() -> dict:
    started = process_start(os.getpid())
    if started in (None, "?"):
        raise FacilityLayoutError("model_store_unavailable", "Cannot identify the import process.", status_code=503)
    return {"pid": os.getpid(), "processStart": started, "created": time.time()}


def live(value) -> bool:
    if (not isinstance(value, dict) or type(value.get("pid")) is not int or value["pid"] <= 0
            or not isinstance(value.get("processStart"), str) or not value["processStart"]):
        return True  # Corruption cannot authorize deletion.
    started = process_start(value.get("pid"))
    return started == "?" or (started is not None and started == value.get("processStart"))


@contextmanager
def coordinator(root: Path):
    """Kernel locks release on process exit; an abandoned lock file is harmless."""
    with _LOCAL:
        lock = safe(root / ".coordinator")
        with lock.open("a+b") as stream:
            if stream.tell() == 0:
                stream.write(b"\0")
                stream.flush()
            deadline = time.monotonic() + 5
            while True:
                try:
                    if os.name == "nt":
                        import msvcrt
                        stream.seek(0)
                        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                    else:
                        import fcntl
                        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise FacilityLayoutError("model_import_busy", "Model storage is busy. Retry shortly.",
                                                  status_code=429) from None
                    time.sleep(.02)
            try:
                yield
            finally:
                if os.name == "nt":
                    import msvcrt
                    stream.seek(0)
                    msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
