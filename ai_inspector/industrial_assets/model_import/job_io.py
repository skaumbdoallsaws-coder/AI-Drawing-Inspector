"""Fixed job filenames shared by the worker and the dependency-free host runner."""
from hashlib import sha256
from pathlib import Path
import stat

from .errors import ModelImportError
from .validation import require

OUTPUT_NAMES = ("summary.json", "cache.json", "parts.npz", "result.json", "error.json")


def local_directory(value) -> Path:
    path = Path(value)
    require(path.is_absolute() and not str(path).startswith(("\\\\", "//")) and ".." not in path.parts,
            "model_worker_failed")
    for item in (path, *path.parents):
        info = item.lstat()
        require(not stat.S_ISLNK(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "model_worker_failed")
    require(path.is_dir(), "model_worker_failed")
    return path.resolve()


def regular_file(job: Path, name: str) -> Path:
    require(name in {*OUTPUT_NAMES, "source.bin", "request.json"}, "model_worker_failed")
    target = job / name
    require(target.resolve().parent == job.resolve(), "model_worker_failed")
    if target.exists() or target.is_symlink():
        info = target.lstat()
        require(stat.S_ISREG(info.st_mode) and not getattr(info, "st_file_attributes", 0) & 0x400,
                "model_worker_failed")
    return target


def bounded_read(job: Path, name: str, maximum: int) -> bytes:
    path = regular_file(job, name)
    require(path.stat().st_size <= maximum, "model_worker_failed")
    with path.open("rb") as stream:
        content = stream.read(maximum + 1)
    require(len(content) <= maximum, "model_worker_failed")
    return content


def file_digest(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()
