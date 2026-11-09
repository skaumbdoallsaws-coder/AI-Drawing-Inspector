"""Transactional draft publication around the isolated prepare worker.

The destination is caller-selected trusted local storage, never recipe data.
Only a complete, validated output folder is renamed there; no existing draft
is overwritten. MI1 supplies scope/admission and translates ModelImportError.
"""
import asyncio
import importlib.util
from pathlib import Path
import stat
import tempfile
import threading

from .errors import ModelImportError
from .job_io import OUTPUT_NAMES, file_digest, local_directory, regular_file
from .limits import DEFAULT_LIMITS, WALL_SECONDS
from .prepare_protocol import DRAFT_FILES, PUBLIC_FIELDS, read_draft_output
from .recipe import normalize_recipe
from .runner import _cancel_and_join, _launch, _result
from .validation import json_bytes, require


def _cancelled(event):
    if event.is_set():
        raise ModelImportError("model_cancelled")


def _source_file(value):
    path = Path(value)
    parent = local_directory(path.parent)
    require(path.name not in {"", ".", ".."} and path.parent.resolve() == parent, "model_worker_failed")
    info = path.lstat()
    require(stat.S_ISREG(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
            "model_worker_failed")
    return path


def _dependencies():
    spec = importlib.util.find_spec("numpy")
    if spec is None or not spec.origin:
        raise ModelImportError("model_runtime_unavailable")
    return local_directory(Path(spec.origin).parent.parent)


def _copy(source, target, event, maximum):
    require(source.stat().st_size <= maximum, "model_too_large")
    total = 0
    with source.open("rb") as src, target.open("xb") as dst:
        while block := src.read(1024 * 1024):
            _cancelled(event)
            total += len(block)
            require(total <= maximum, "model_too_large")
            dst.write(block)


def _remove_owned_draft(destination):
    """Fixed owned files only; preserve unexpected files instead of recursive deletion."""
    try:
        directory = local_directory(destination)
        for name in {*DRAFT_FILES, "manifest.json"}:
            regular_file(directory, name).unlink(missing_ok=True)
        directory.rmdir()
    except (ModelImportError, OSError):
        pass


def prepare_draft(source_path: str | Path, recipe: dict, out_dir: str | Path,
                  cancel: threading.Event | None = None, *, dependency_root: str | Path | None = None,
                  cache_dir: str | Path | None = None, timeout: float = WALL_SECONDS,
                  _published: threading.Event | None = None) -> dict:
    """Return <=48 KiB public summary; frozen full metadata lives in out_dir/draft.json.

    Optional dependency_root/cache_dir are trusted host configuration, not recipe
    fields. If no cache is supplied, the same limited worker first runs inspect.
    """
    normalized = normalize_recipe(recipe)
    event = cancel if cancel is not None else threading.Event()
    _cancelled(event)
    destination = Path(out_dir)
    published, success, lock_owned = False, False, False
    lock = None
    try:
        parent = local_directory(destination.parent)
        require(destination.name not in {"", ".", ".."} and destination.parent.resolve() == parent, "model_worker_failed")
        require(not destination.exists() and not destination.is_symlink(), "model_destination_exists")
        source = _source_file(source_path)
        dependencies = _dependencies() if dependency_root is None else local_directory(dependency_root)
        lock = parent / (destination.name + ".prepare-lock")
        try:
            with lock.open("xb") as stream:
                stream.write(b"model-import prepare\n")
            lock_owned = True
        except FileExistsError:
            raise ModelImportError("model_destination_exists") from None
        with tempfile.TemporaryDirectory(prefix=".model-prepare-", dir=parent) as temporary:
            job = local_directory(temporary)
            require(job.parent == parent, "model_worker_failed")
            _copy(source, job / "source.bin", event, DEFAULT_LIMITS.upload_bytes)
            source_hash = file_digest(job / "source.bin")
            (job / "recipe.json").write_bytes(json_bytes(normalized))
            if cache_dir is not None:
                cached = local_directory(cache_dir)
                summary = _result(cached)
                require(summary["sourceSha256"] == source_hash, "model_cache_invalid")
                for name in OUTPUT_NAMES:
                    if name != "error.json":
                        _copy(_source_file(cached / name), job / name, event, 384 * 1024 * 1024)
            _launch(job, dependencies, "prepare", event, timeout)
            draft = read_draft_output(job / "output")
            require(draft["recipe"] == normalized and draft["sourceSha256"] == source_hash, "model_worker_failed")
            _cancelled(event)
            require(not destination.exists() and not destination.is_symlink(), "model_destination_exists")
            (job / "output").rename(destination)
            published = True
            if _published is not None:
                _published.set()
            _cancelled(event)
            result = {key: draft[key] for key in PUBLIC_FIELDS}
        _cancelled(event)
        success = True
        return result
    except OSError:
        raise ModelImportError("model_worker_failed") from None
    finally:
        if published and not success:
            _remove_owned_draft(destination)
        if lock_owned:
            lock.unlink(missing_ok=True)


async def prepare_draft_async(source_path: str | Path, recipe: dict, out_dir: str | Path,
                              cancel: threading.Event | None = None, **options) -> dict:
    event = cancel if cancel is not None else threading.Event()
    published = threading.Event()
    work = asyncio.create_task(asyncio.to_thread(prepare_draft, source_path, recipe, out_dir, event,
                                               _published=published, **options))
    try:
        await asyncio.wait({work})
        return work.result()
    except asyncio.CancelledError:
        await _cancel_and_join(work, event)
        if published.is_set():
            _remove_owned_draft(Path(out_dir))
        raise
