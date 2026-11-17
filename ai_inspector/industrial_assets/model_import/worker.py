"""Isolated CLI: python -I -S -B worker.py <dependency_root> <job_dir> inspect|prepare|build.

Only stdlib imports precede limits. No app package or site startup is executed.
"""
import importlib.util
import os
from pathlib import Path
import sys

CPU_SECONDS = 60
MEMORY_BYTES = 1536 * 1024 * 1024
OPEN_FILES = 64
_JOB = None


def limit_resources() -> bool:
    """Fail closed on both platforms; the Windows handle lives until process exit."""
    global _JOB
    try:
        if os.name != "nt":
            import resource
            for kind, ceiling in ((resource.RLIMIT_CPU, CPU_SECONDS), (resource.RLIMIT_AS, MEMORY_BYTES),
                                  (resource.RLIMIT_NOFILE, OPEN_FILES), (resource.RLIMIT_CORE, 0)):
                _, hard = resource.getrlimit(kind)
                maximum = ceiling if hard == resource.RLIM_INFINITY else min(hard, ceiling)
                resource.setrlimit(kind, (maximum, maximum))
            return True
        import ctypes
        from ctypes import wintypes

        class Basic(ctypes.Structure):
            _fields_ = [("process_time", ctypes.c_int64), ("job_time", ctypes.c_int64),
                        ("flags", wintypes.DWORD), ("min_ws", ctypes.c_size_t), ("max_ws", ctypes.c_size_t),
                        ("processes", wintypes.DWORD), ("affinity", ctypes.c_size_t),
                        ("priority", wintypes.DWORD), ("scheduling", wintypes.DWORD)]

        class IO(ctypes.Structure):
            _fields_ = [(key, ctypes.c_uint64) for key in
                        ("read_ops", "write_ops", "other_ops", "read_bytes", "write_bytes", "other_bytes")]

        class Extended(ctypes.Structure):
            _fields_ = [("basic", Basic), ("io", IO), ("process_memory", ctypes.c_size_t),
                        ("job_memory", ctypes.c_size_t), ("peak_process", ctypes.c_size_t),
                        ("peak_job", ctypes.c_size_t)]

        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.CreateJobObjectW.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
        kernel.CreateJobObjectW.restype = wintypes.HANDLE
        kernel.SetInformationJobObject.argtypes = (wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD)
        kernel.SetInformationJobObject.restype = wintypes.BOOL
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        kernel.AssignProcessToJobObject.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
        kernel.AssignProcessToJobObject.restype = wintypes.BOOL
        kernel.CloseHandle.argtypes = (wintypes.HANDLE,)
        job = kernel.CreateJobObjectW(None, None)
        info = Extended()
        info.basic.flags = 0x2 | 0x8 | 0x100 | 0x2000
        info.basic.process_time = CPU_SECONDS * 10_000_000
        info.basic.processes = 1
        info.process_memory = MEMORY_BYTES
        if (not job or not kernel.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info))
                or not kernel.AssignProcessToJobObject(job, kernel.GetCurrentProcess())):
            if job:
                kernel.CloseHandle(job)
            return False
        _JOB = job
        return True
    except (OSError, ValueError, OverflowError, ImportError, AttributeError):
        return False


def _build(job, job_io, task_name="build"):
    """Builder and reference tasks bootstrap the second private package."""
    package = Path(__file__).resolve().parent.parent / "model_builder"
    spec = importlib.util.spec_from_file_location("_model_builder_worker", package / "__init__.py",
                                                 submodule_search_locations=[str(package)])
    builder = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = builder
    spec.loader.exec_module(builder)
    try:
        task = importlib.import_module(".worker_task" if task_name == "build" else ".reference_worker", spec.name)
        if task_name == "build":
            task.execute_build(job)
        else:
            task.execute_reference(job)
    except builder.ModelBuildError as error:
        errors = importlib.import_module(".errors", spec.name)
        payload = errors.json_bytes(error.to_dict())
        errors.decode_error(payload)  # Also enforces the 8 KiB refusal ceiling.
        with job_io.regular_file(job, "error.json").open("xb") as stream:
            stream.write(payload)
        return 2
    return 0


def main(argv=None) -> int:
    if not limit_resources():
        return 4
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3 or argv[2] not in {"inspect", "prepare", "build", "reference"}:
        return 1
    dependencies, job = Path(argv[0]), Path(argv[1])
    if not dependencies.is_absolute() or not job.is_absolute():
        return 1
    # Load this directory as a private package without running industrial_assets.__init__.
    package = Path(__file__).resolve().parent
    spec = importlib.util.spec_from_file_location("_model_import_worker", package / "__init__.py",
                                                 submodule_search_locations=[str(package)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    job_io = importlib.import_module(".job_io", spec.name)
    try:
        dependencies = job_io.local_directory(dependencies)
        job = job_io.local_directory(job)
        # Append directly: no .pth, sitecustomize, PYTHONPATH or cwd lookup.
        sys.path.append(str(dependencies))
        if argv[2] in {"build", "reference"}:
            return _build(job, job_io, argv[2])
        task = importlib.import_module(".worker_task", spec.name)
        if argv[2] == "inspect":
            task.execute_inspect(job)
        else:
            prepare = importlib.import_module(".prepare", spec.name)
            prepare.execute_prepare(job)
    except ImportError:
        return 3
    except module.ModelImportError as error:
        validation = importlib.import_module(".validation", spec.name)
        try:
            with job_io.regular_file(job, "error.json").open("xb") as stream:
                stream.write(validation.json_bytes(error.to_dict()))
        except (OSError, module.ModelImportError):
            return 1
        return 2
    except MemoryError:
        return 1
    except Exception:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
