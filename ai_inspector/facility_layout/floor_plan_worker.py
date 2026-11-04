"""Floor-plan import, worker (docs/facility-floor-plan-import-plan.md, section 10, "Untrusted input").

`parse_dxf` reads an uploaded DXF in a separate process that can be killed: a timed-out thread that keeps running
would not do. The child is `python -E -B -c <bootstrap>`, which loads floor_plan_reader.py by its path (so the app's
package, with its heavy imports, is never imported there) and calls its `worker_main`. The child:

- has no console window (CREATE_NO_WINDOW) and its working directory is the job's own folder, which holds nothing
  importable;
- runs, on Windows, inside a job object that caps its memory (the plan's 512 MiB ceiling) and kills it when the job
  is closed, so it never outlives this call; past the wall-clock limit the job is terminated;
- ignores PYTHON* environment variables (-E) and reads nothing but the DXF: no network, no external references, no
  linked files (the reader never opens any other path).

The result is two files in the job folder, geometry.json (everything) and manifest.json (everything but the
entities), plus the peak memory the child used, for the benchmarks.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

READER_PATH = Path(__file__).with_name("floor_plan_reader.py")
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MEMORY_MB = 512
_CREATE_NO_WINDOW = 0x08000000
# The child waits for one byte on stdin before it touches the drawing: the parent sends it only once the child is
# inside its job object, so not a byte of the DXF is read without the memory cap.
_BOOTSTRAP = (
    "import sys\n"
    "if sys.stdin.buffer.read(1) != b'1':\n"
    "    raise SystemExit(5)\n"
    "import importlib.util\n"
    "spec = importlib.util.spec_from_file_location('inspectorpro_floor_plan_reader', sys.argv[1])\n"
    "module = importlib.util.module_from_spec(spec)\n"
    "spec.loader.exec_module(module)\n"
    "raise SystemExit(module.worker_main(sys.argv[2:]))\n"
)


class FloorPlanParseError(Exception):
    """The drawing could not be imported. `code` is stable for the API; `message` is safe to show the user."""

    def __init__(self, code: str, message: str, *, status_code: int = 422, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}


class _WindowsJob:
    """A job object holding one process: a per-process memory cap, and every process in it dies when it closes."""

    def __init__(self, memory_bytes: int):
        import ctypes
        from ctypes import wintypes

        self._ctypes = ctypes
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._kernel32 = kernel32

        class Basic(ctypes.Structure):
            _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                        ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                        ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                        ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                        ("SchedulingClass", wintypes.DWORD)]

        class Io(ctypes.Structure):
            _fields_ = [(name, ctypes.c_uint64) for name in (
                "ReadOperationCount", "WriteOperationCount", "OtherOperationCount", "ReadTransferCount",
                "WriteTransferCount", "OtherTransferCount")]

        class Extended(ctypes.Structure):
            _fields_ = [("BasicLimitInformation", Basic), ("IoInfo", Io), ("ProcessMemoryLimit", ctypes.c_size_t),
                        ("JobMemoryLimit", ctypes.c_size_t), ("PeakProcessMemoryUsed", ctypes.c_size_t),
                        ("PeakJobMemoryUsed", ctypes.c_size_t)]

        self._Extended = Extended
        kernel32.CreateJobObjectW.restype = wintypes.HANDLE
        kernel32.CreateJobObjectW.argtypes = [ctypes.c_void_p, wintypes.LPCWSTR]
        kernel32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        kernel32.QueryInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                                       wintypes.DWORD, ctypes.c_void_p]
        kernel32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        kernel32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        self.handle = kernel32.CreateJobObjectW(None, None)
        if not self.handle:
            raise OSError(ctypes.get_last_error(), "CreateJobObject failed")
        info = Extended()
        # PROCESS_MEMORY | DIE_ON_UNHANDLED_EXCEPTION | KILL_ON_JOB_CLOSE
        info.BasicLimitInformation.LimitFlags = 0x100 | 0x400 | 0x2000
        info.ProcessMemoryLimit = memory_bytes
        if not kernel32.SetInformationJobObject(self.handle, 9, ctypes.byref(info), ctypes.sizeof(info)):
            error = ctypes.get_last_error()
            self.close()
            raise OSError(error, "SetInformationJobObject failed")

    def assign(self, pid: int) -> None:
        process = self._kernel32.OpenProcess(0x0100 | 0x0001, False, pid)  # PROCESS_SET_QUOTA | PROCESS_TERMINATE
        if not process:
            raise OSError(self._ctypes.get_last_error(), "OpenProcess failed")
        try:
            if not self._kernel32.AssignProcessToJobObject(self.handle, process):
                raise OSError(self._ctypes.get_last_error(), "AssignProcessToJobObject failed")
        finally:
            self._kernel32.CloseHandle(process)

    def peak_memory(self) -> int | None:
        info = self._Extended()
        ok = self._kernel32.QueryInformationJobObject(self.handle, 9, self._ctypes.byref(info),
                                                      self._ctypes.sizeof(info), None)
        return int(info.PeakProcessMemoryUsed) if ok else None

    def terminate(self) -> None:
        if self.handle:
            self._kernel32.TerminateJobObject(self.handle, 1)

    def close(self) -> None:
        if self.handle:
            self._kernel32.CloseHandle(self.handle)  # KILL_ON_JOB_CLOSE: nothing in the job survives this
            self.handle = None


def _posix_limits(memory_bytes: int):  # pragma: no cover - the app runs on Windows
    def apply():
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (memory_bytes, memory_bytes))
    return apply


def _child_environment() -> dict:
    keep = {}
    for key, value in os.environ.items():
        # -E ignores PYTHON* anyway; EZDXF* could point ezdxf at another config file.
        if key.upper().startswith(("PYTHON", "EZDXF")):
            continue
        keep[key] = value
    keep["PYTHONDONTWRITEBYTECODE"] = "1"
    keep["PYTHONIOENCODING"] = "utf-8"
    # ezdxf imports numpy, whose OpenBLAS reserves a buffer for every CPU thread at import (hundreds of MB on a
    # many-core machine, and a hang instead of an error when the memory cap refuses it). The reader does no linear
    # algebra worth threads.
    for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
        keep[name] = "1"
    return keep


def _read_json(path: Path) -> dict | None:
    try:
        with open(path, "r", encoding="utf-8") as handle:
            value = json.load(handle)
        return value if isinstance(value, dict) else None
    except (OSError, ValueError):
        return None


def parse_dxf(dxf_path: str | os.PathLike, work_dir: str | os.PathLike, *, source_sha256: str | None = None,
              timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS, memory_mb: int = DEFAULT_MEMORY_MB,
              reader_limits: dict | None = None, python: str | None = None) -> dict:
    """Read DXF_PATH in a worker process; outputs land in WORK_DIR (an existing folder used only by this job).
    Returns {"geometryPath", "manifestPath", "manifest", "seconds", "peakMemoryBytes"}; raises FloorPlanParseError."""
    work = Path(work_dir)
    for name in ("geometry.json", "manifest.json", "error.json"):
        (work / name).unlink(missing_ok=True)
    memory_bytes = int(memory_mb) * 1024 * 1024
    args = [python or sys.executable, "-E", "-B", "-c", _BOOTSTRAP, str(READER_PATH), str(Path(dxf_path).resolve()),
            str(work.resolve()), json.dumps(reader_limits or {}), source_sha256 or ""]
    stderr_path = work / "worker-stderr.txt"
    job = None
    started = time.monotonic()
    timed_out = False
    peak = None
    with open(stderr_path, "wb") as stderr:
        popen_kwargs = {"cwd": str(work), "env": _child_environment(), "stdin": subprocess.PIPE,
                        "stdout": subprocess.DEVNULL, "stderr": stderr}
        if os.name == "nt":
            popen_kwargs["creationflags"] = _CREATE_NO_WINDOW
            try:
                job = _WindowsJob(memory_bytes)
            except OSError as error:
                raise FloorPlanParseError("parse_unavailable", "The drawing reader could not be started.",
                                          status_code=503, details={"reason": str(error)[:200]}) from None
        else:  # pragma: no cover
            popen_kwargs["preexec_fn"] = _posix_limits(memory_bytes)
        try:
            process = subprocess.Popen(args, **popen_kwargs)
        except (OSError, PermissionError) as error:
            if job is not None:
                job.close()
            raise FloorPlanParseError("parse_unavailable", "The drawing reader could not be started.",
                                      status_code=503, details={"reason": str(error)[:200]}) from None
        try:
            if job is not None:
                try:
                    job.assign(process.pid)
                except OSError:
                    process.kill()
                    process.wait()
                    raise FloorPlanParseError("parse_unavailable", "The drawing reader could not be limited, so it "
                                              "was not run.", status_code=503) from None
            try:
                process.stdin.write(b"1")  # go: the child is inside its limits now
                process.stdin.close()
            except OSError:
                pass  # it already exited; its exit code tells the story
            try:
                process.wait(timeout=timeout_seconds)
            except subprocess.TimeoutExpired:
                timed_out = True
                if job is not None:
                    job.terminate()
                process.kill()
                process.wait()
        finally:
            if job is not None:
                peak = job.peak_memory()
                job.close()
            elif process.poll() is None:  # pragma: no cover
                process.kill()
                process.wait()
    seconds = round(time.monotonic() - started, 3)
    if timed_out:
        raise FloorPlanParseError("parse_timeout", f"Reading the drawing took longer than {timeout_seconds:g} "
                                  "seconds, so it was stopped. Try a smaller drawing or remove unused layers.",
                                  details={"seconds": seconds})
    error = _read_json(work / "error.json")
    if process.returncode == 0:
        manifest = _read_json(work / "manifest.json")
        if manifest is not None and (work / "geometry.json").is_file():
            return {"geometryPath": str(work / "geometry.json"), "manifestPath": str(work / "manifest.json"),
                    "manifest": manifest, "seconds": seconds, "peakMemoryBytes": peak}
    if error and isinstance(error.get("code"), str) and isinstance(error.get("message"), str):
        status = 413 if error["code"] in ("too_large", "too_many_entities", "too_many_vertices",
                                          "too_many_layers") else 422
        raise FloorPlanParseError(error["code"][:64], error["message"][:500], status_code=status,
                                  details={"seconds": seconds, "peakMemoryBytes": peak})
    tail = _tail(stderr_path)
    if (peak is not None and peak >= memory_bytes * 0.9) or "MemoryError" in tail:
        raise FloorPlanParseError("too_large", f"Reading the drawing needed more than {memory_mb} MiB of memory, "
                                  "more than the import allows.", status_code=413,
                                  details={"seconds": seconds, "peakMemoryBytes": peak})
    # stderrTail is for the server log only; the API never returns it (it can hold local paths).
    raise FloorPlanParseError("parse_failed", "The drawing reader stopped unexpectedly.",
                              details={"seconds": seconds, "exitCode": process.returncode, "stderrTail": tail})


def _tail(path: Path, limit: int = 2000) -> str:
    try:
        data = path.read_bytes()[-limit:]
    except OSError:
        return ""
    return data.decode("utf-8", errors="replace")
