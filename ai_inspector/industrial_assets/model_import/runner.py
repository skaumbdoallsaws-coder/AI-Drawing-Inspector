"""Host-owned worker launch: no source parsing or numerical imports in this module."""
import asyncio
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

from .errors import MESSAGES, ModelImportError
from .cleanup import retry_cleanup
from .process_tree import ProcessTree, base_executable
from .job_io import OUTPUT_NAMES, bounded_read, file_digest, local_directory, regular_file
from .limits import PREVIEW_BYTES, WALL_SECONDS
from .protocol import read_summary, validate_manifest
from .pictures import validate_picture
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


def _clean_outputs(job: Path) -> None:
    for name in OUTPUT_NAMES:
        try:
            retry_cleanup(lambda: regular_file(job, name).unlink(missing_ok=True))
        except (OSError, ModelImportError):
            pass


def _result(job: Path, *, require_preview: bool = False) -> dict:
    try:
        manifest = validate_manifest(parse_json(bounded_read(job, "result.json", 4096), 4096))
        for name, entry in manifest["files"].items():
            file = regular_file(job, name)
            require(file.stat().st_size == entry["bytes"] and file_digest(file) == entry["sha256"],
                    "model_worker_failed")
        require(not require_preview or manifest["schemaVersion"] == 2, "model_worker_failed")
        if "preview.png" in manifest["files"]:
            validate_picture(bounded_read(job, "preview.png", PREVIEW_BYTES), "preview")
        return read_summary(bounded_read(job, "summary.json", 48 * 1024))
    except (ModelImportError, OSError, ValueError, TypeError, KeyError):
        raise ModelImportError("model_worker_failed") from None


def _launch(job, dependency_root, task, event, timeout):
    """One process and one wall clock for either task; always kill and join on failure."""
    if not 0 < timeout <= WALL_SECONDS:
        raise ValueError("Worker timeout must be positive and at most 70 seconds")
    if event.is_set():
        raise ModelImportError("model_cancelled")
    executable = base_executable()
    process = None
    try:
        tree = ProcessTree()
    except (OSError, AttributeError):
        raise ModelImportError("model_limits_unavailable") from None
    try:
        started = time.monotonic()
        process = subprocess.Popen(
            [executable, "-I", "-S", "-B", str(_WORKER), str(dependency_root), str(job), task],
            cwd=job, env=worker_environment(job, executable), stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            start_new_session=os.name != "nt")
        tree.attach(process)
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
                error = parse_json(bounded_read(job, "error.json", 8192), 8192)
                require(isinstance(error.get("code"), str) and error["code"] in MESSAGES, "model_worker_failed")
                refusal = ModelImportError(error["code"], error.get("details"))
                require(error == refusal.to_dict(), "model_worker_failed")
            except (ModelImportError, OSError, ValueError):
                raise ModelImportError("model_worker_failed") from None
            raise refusal
        require(code == 0, "model_worker_failed")
    except OSError:
        raise ModelImportError("model_worker_failed") from None
    finally:
        active_error = sys.exc_info()[0] is not None
        try:
            if process is not None:
                tree.stop(process)
        except OSError:
            if not active_error:
                raise ModelImportError("model_worker_failed") from None
        finally:
            tree.close()


def run_inspect(job_dir: str | Path, dependency_root: str | Path, *,
                cancel_event: threading.Event | None = None, timeout: float = WALL_SECONDS,
                _owned: threading.Event | None = None) -> dict:
    """Inspect source.bin in a fresh caller-owned job; retain successful MI0a caches."""
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
    if _owned is not None:
        _owned.set()
    success = False
    try:
        _launch(job, dependency_root, "inspect", event, timeout)
        result = _result(job, require_preview=True)
        if event.is_set():
            raise ModelImportError("model_cancelled")
        success = True
        return result
    finally:
        if not success:
            _clean_outputs(job)


async def _cancel_and_join(work, event):
    event.set()
    while not work.done():
        try:
            await asyncio.wait({work})
        except asyncio.CancelledError:
            continue
        except Exception:
            break
    if work.done() and not work.cancelled():
        work.exception()


async def run_inspect_async(job_dir: str | Path, dependency_root: str | Path, *,
                            cancel_event: threading.Event | None = None, timeout: float = WALL_SECONDS) -> dict:
    """Cancellation owns cleanup even when it wins delivery of a successful result."""
    event = cancel_event if cancel_event is not None else threading.Event()
    owned = threading.Event()
    work = asyncio.create_task(asyncio.to_thread(run_inspect, job_dir, dependency_root,
                                               cancel_event=event, timeout=timeout, _owned=owned))
    try:
        await asyncio.wait({work})
        return work.result()
    except asyncio.CancelledError:
        await _cancel_and_join(work, event)
        if owned.is_set():
            try:
                _clean_outputs(local_directory(job_dir))
            except (OSError, ModelImportError):
                pass
        raise


def prepare_draft(source_path, recipe, out_dir, cancel=None, **options):
    """Public convenience entry; see prepare_runner for runtime/cache options."""
    from .prepare_runner import prepare_draft as prepare
    return prepare(source_path, recipe, out_dir, cancel, **options)


async def prepare_draft_async(source_path, recipe, out_dir, cancel=None, **options):
    from .prepare_runner import prepare_draft_async as prepare
    return await prepare(source_path, recipe, out_dir, cancel, **options)
