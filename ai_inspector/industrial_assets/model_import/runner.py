"""Host-owned worker launch: no source parsing or numerical imports in this module."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .errors import MESSAGES, ModelImportError
from .job_io import OUTPUT_NAMES, bounded_read, file_digest, local_directory, regular_file
from .limits import WALL_SECONDS
from .protocol import read_summary, validate_manifest
from .validation import parse_json, require

_WORKER = Path(__file__).with_name("worker.py")


def worker_environment(job: Path, executable: str) -> dict[str, str]:
    environment = {key: str(job) for key in ("HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR", "APPDATA", "LOCALAPPDATA")}
    environment.update(PATH=str(Path(executable).parent), OMP_NUM_THREADS="1", OPENBLAS_NUM_THREADS="1",
                       MKL_NUM_THREADS="1", NUMEXPR_NUM_THREADS="1")
    if os.name == "nt":
        system = os.environ.get("SystemRoot", os.environ.get("SYSTEMROOT", "C:/Windows"))
        environment.update(SYSTEMROOT=system, WINDIR=system)
        environment["PATH"] += os.pathsep + str(Path(system) / "System32")
    return environment


def _join(process) -> None:
    if process.poll() is None:
        process.kill()
    process.wait()


def _clean_outputs(job: Path) -> None:
    for name in OUTPUT_NAMES:
        try:
            regular_file(job, name).unlink(missing_ok=True)
        except (OSError, ModelImportError):
            pass


def _result(job: Path) -> dict:
    try:
        manifest = validate_manifest(parse_json(bounded_read(job, "result.json", 4096), 4096))
        for name, entry in manifest["files"].items():
            file = regular_file(job, name)
            require(file.stat().st_size == entry["bytes"] and file_digest(file) == entry["sha256"],
                    "model_worker_failed")
        return read_summary(bounded_read(job, "summary.json", 48 * 1024))
    except (ModelImportError, OSError, ValueError, TypeError, KeyError):
        raise ModelImportError("model_worker_failed") from None


def run_inspect(job_dir: str | Path, dependency_root: str | Path, *,
                cancel_event: threading.Event | None = None, timeout: float = WALL_SECONDS) -> dict:
    """Inspect source.bin in a fresh caller-owned job directory.

    dependency_root comes from trusted host configuration (later glb_runtime().
    dependency_root), never the uploaded model. Successful caches remain for MI0b.
    Failed/cancelled output files are removed; the caller owns source/job cleanup.
    """
    if not 0 < timeout <= WALL_SECONDS:
        raise ValueError("Worker timeout must be positive and at most 70 seconds")
    event = cancel_event if cancel_event is not None else threading.Event()
    if event.is_set():
        raise ModelImportError("model_cancelled")
    try:
        job = local_directory(job_dir)
        dependency_root = local_directory(dependency_root)
        require(regular_file(job, "source.bin").is_file(), "model_worker_failed")
        require(not any(regular_file(job, name).exists() for name in OUTPUT_NAMES), "model_worker_failed")
    except OSError:
        raise ModelImportError("model_worker_failed") from None
    process, success = None, False
    try:
        started = time.monotonic()
        process = subprocess.Popen(
            [sys.executable, "-I", "-S", "-B", str(_WORKER), str(dependency_root), str(job), "inspect"],
            cwd=job, env=worker_environment(job, sys.executable), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        while True:
            if event.is_set():
                raise ModelImportError("model_cancelled")
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise ModelImportError("model_timeout")
            try:
                code = process.wait(timeout=min(0.2, remaining))
                break
            except subprocess.TimeoutExpired:
                continue
        if event.is_set():
            raise ModelImportError("model_cancelled")
        if code == 4:
            raise ModelImportError("model_limits_unavailable")
        if code == 3:
            raise ModelImportError("model_runtime_unavailable")
        if code == 2:
            try:
                error = parse_json(bounded_read(job, "error.json", 2048), 2048)
                require(isinstance(error.get("code"), str) and error["code"] in MESSAGES, "model_worker_failed")
                refusal = ModelImportError(error["code"])
                require(error == refusal.to_dict(), "model_worker_failed")
            except (ModelImportError, OSError):
                raise ModelImportError("model_worker_failed") from None
            raise refusal
        require(code == 0, "model_worker_failed")
        result = _result(job)
        if event.is_set():
            raise ModelImportError("model_cancelled")
        success = True
        return result
    except OSError:
        raise ModelImportError("model_worker_failed") from None
    finally:
        if process is not None:
            _join(process)
        if not success:
            _clean_outputs(job)


async def run_inspect_async(job_dir: str | Path, dependency_root: str | Path, *,
                            cancel_event: threading.Event | None = None, timeout: float = WALL_SECONDS) -> dict:
    """Propagate task cancellation to the synchronous runner, then join its thread."""
    event = cancel_event if cancel_event is not None else threading.Event()
    work = asyncio.create_task(asyncio.to_thread(run_inspect, job_dir, dependency_root,
                                               cancel_event=event, timeout=timeout))
    try:
        return await asyncio.shield(work)
    except asyncio.CancelledError:
        event.set()
        while not work.done():
            try:
                await asyncio.shield(work)
            except asyncio.CancelledError:
                continue
            except Exception:
                break
        if work.done() and not work.cancelled():
            work.exception()
        raise
