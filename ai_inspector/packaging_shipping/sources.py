"""Bounded, self-contained GLB ingestion; mass is never inferred from a shell."""
import asyncio
from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig
from tempfile import TemporaryDirectory

from .service import PackagingError
from .glb_worker import MAX_BYTES, ImportRejected, convert

_WORKER = Path(__file__).with_name('glb_worker.py')
_RUNTIME = None


@dataclass(frozen=True)
class GlbRuntime:
    dependency_root: Path

    def __post_init__(self):
        path = Path(self.dependency_root)
        if not path.is_absolute() or str(path).startswith('\\\\') or '..' in path.parts:
            raise ValueError('glb_dependency_root_invalid')
        for item in (path, *path.parents):
            if item.is_symlink() or getattr(item, 'is_junction', lambda: False)():
                raise ValueError('glb_dependency_root_invalid')
        if not path.is_dir():
            raise ValueError('glb_dependency_root_invalid')
        object.__setattr__(self, 'dependency_root', path.resolve())


def configure_glb_runtime(dependency_root=None):
    """Bind only from trusted host startup, using the already validated profile."""
    global _RUNTIME
    _RUNTIME = None if dependency_root is None else GlbRuntime(dependency_root)


def glb_runtime():
    # Non-native hosts retain interpreter-installed dependencies, never PYTHONPATH
    # or user site discovery. Native startup supplies its explicit release bundle.
    return _RUNTIME or GlbRuntime(Path(sysconfig.get_path('purelib')))


def import_glb(payload: bytes, name: str, meters_per_unit: float):
    try:
        return convert(payload, name, meters_per_unit)
    except ImportRejected as exc:
        raise PackagingError(exc.code, exc.message, exc.status) from exc


async def import_glb_isolated(payload, name, meters_per_unit, root, *, runtime=None):
    """A cancelled/slow model parse cannot leave a thread editing the workspace."""
    if meters_per_unit not in (1.0, 0.001, 0.0254):
        raise PackagingError("units_required", "Choose meters, millimeters or inches for the model's stored coordinates.", 400)
    runtime = glb_runtime() if runtime is None else runtime
    if not isinstance(runtime, GlbRuntime):
        raise TypeError('A host-configured GlbRuntime is required')
    directory = Path(root).resolve() / "import-jobs"
    directory.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(prefix="glb-", dir=directory) as temp:
        job = Path(temp)
        (job / "input.glb").write_bytes(payload)
        system = os.environ.get('SystemRoot', os.environ.get('SYSTEMROOT', 'C:/Windows'))
        env = {key: str(job) for key in ('HOME', 'USERPROFILE', 'TMP', 'TEMP', 'TMPDIR', 'APPDATA', 'LOCALAPPDATA')}
        env.update(PATH=str(Path(sys.executable).parent), OMP_NUM_THREADS='1', OPENBLAS_NUM_THREADS='1', MKL_NUM_THREADS='1')
        if os.name == 'nt':
            env.update(SYSTEMROOT=system, WINDIR=system)
            env['PATH'] += os.pathsep + str(Path(system) / 'System32')
        process = await asyncio.create_subprocess_exec(
            sys.executable, '-I', '-S', '-B', str(_WORKER), str(runtime.dependency_root), str(job), str(meters_per_unit),
            cwd=job, env=env, stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            await asyncio.wait_for(process.wait(), timeout=25)
        except (TimeoutError, asyncio.CancelledError):
            if process.returncode is None:
                process.kill()
            await process.wait()
            if asyncio.current_task().cancelling():
                raise
            raise PackagingError("source_timeout", "Model import exceeded its time limit. Use a smaller static GLB.", 422)
        if process.returncode == 3:
            raise PackagingError("source_runtime_unavailable", "Model import is not available in this installation: a "
                                 "required component is missing. Manual dimensions still work.", 503)
        if process.returncode != 0 or not (job / "metadata.json").is_file():
            raise PackagingError("source_invalid", "The model could not be imported. Check its format, units and complexity.", 422)
        metadata = json.loads((job / "metadata.json").read_text(encoding="utf-8"))
        metadata["name"] = name[:160] or "Imported product"
        result = job / "normalized.glb"
        if result.stat().st_size > MAX_BYTES * 2:
            raise PackagingError("source_too_large", "Normalized geometry exceeds the import size limit.", 413)
        return metadata, result.read_bytes()
