"""Worker boundary tests: real subprocesses plus fast generated-fixture task calls."""
import ast
import asyncio
from copy import deepcopy
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import numpy as np
import pytest

from tests.model_import_test_support import PACKAGE, Fixture, module, textured_box

runner = module("runner")
worker = module("worker")
task = module("worker_task")
cache = module("cache")
protocol = module("protocol")
job_io = module("job_io")
ModelImportError = module("errors").ModelImportError
DEPENDENCIES = Path(np.__file__).resolve().parent.parent


def make_job(tmp_path, payload=None):
    job = tmp_path / "job"
    job.mkdir()
    if payload is None:
        fixture = Fixture()
        fixture.triangle()
        payload = fixture.bytes()
    (job / "source.bin").write_bytes(payload)
    return job


def substitute_worker(tmp_path, monkeypatch, code):
    file = tmp_path / "stub.py"
    file.write_bytes(code.encode("utf-8"))
    monkeypatch.setattr(runner, "_WORKER", file)


def test_in_process_task_and_cache_round_trip(tmp_path):
    job = make_job(tmp_path, textured_box().bytes())
    result = task.execute_inspect(job)
    restored = cache.load_cache(job)
    assert result["triangles"] == 12 and result["partsTotal"] == 1
    assert restored.images[0].data.startswith(b"\x89PNG")
    np.testing.assert_allclose(restored.parts[0].positions, module("reader").read_model(textured_box().bytes()).parts[0].positions)
    assert runner._result(job) == result
    with np.load(job / "parts.npz", allow_pickle=False) as values:
        assert all(values[name].dtype.kind != "O" for name in values.files)


def test_real_worker_inspect(tmp_path):
    job = make_job(tmp_path, textured_box().bytes())
    (job / "request.json").write_bytes(b'{"name":"box.glb"}')
    result = runner.run_inspect(job, DEPENDENCIES)
    assert result["name"] == "box.glb" and result["triangles"] == 12
    assert cache.load_cache(job).images[0].width == 8
    assert not list(job.glob("*.pyc"))


def test_real_worker_refusal_is_bounded_and_keeps_source(tmp_path):
    job = make_job(tmp_path, b"unsupported")
    with pytest.raises(ModelImportError) as caught:
        runner.run_inspect(job, DEPENDENCIES)
    assert caught.value.code == "model_format_unsupported"
    assert sorted(p.name for p in job.iterdir()) == ["source.bin"]


def test_real_worker_missing_dependency_maps_to_runtime_error(tmp_path):
    job = make_job(tmp_path)
    dependencies = tmp_path / "empty"
    dependencies.mkdir()
    with pytest.raises(ModelImportError) as caught:
        runner.run_inspect(job, dependencies)
    assert caught.value.code == "model_runtime_unavailable"


def test_limits_fail_closed_before_task_import_or_source_read(monkeypatch):
    monkeypatch.setattr(worker, "limit_resources", lambda: False)
    monkeypatch.setattr(worker.importlib.util, "spec_from_file_location",
                        lambda *a, **k: pytest.fail("package loaded without limits"))
    assert worker.main(["unread-dependencies", "unread-job", "inspect"]) == 4


@pytest.mark.parametrize("exit_code,expected", [(1, "model_worker_failed"), (3, "model_runtime_unavailable"),
                                               (4, "model_limits_unavailable"), (17, "model_worker_failed")])
def test_exit_mapping(tmp_path, monkeypatch, exit_code, expected):
    job = make_job(tmp_path)
    substitute_worker(tmp_path, monkeypatch, f"raise SystemExit({exit_code})\n")
    with pytest.raises(ModelImportError) as caught:
        runner.run_inspect(job, DEPENDENCIES)
    assert caught.value.code == expected


@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_and_cancellation_kill_and_join(tmp_path, monkeypatch, cancel):
    job = make_job(tmp_path)
    substitute_worker(tmp_path, monkeypatch, "import time\nfrom pathlib import Path\n"
                      "Path('summary.json').write_text('{}')\ntime.sleep(30)\n")
    processes = []
    original = subprocess.Popen

    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process

    monkeypatch.setattr(runner.subprocess, "Popen", capture)
    event = threading.Event()
    timer = threading.Timer(0.15, event.set) if cancel else None
    if timer:
        timer.start()
    started = time.monotonic()
    try:
        with pytest.raises(ModelImportError) as caught:
            runner.run_inspect(job, DEPENDENCIES, cancel_event=event, timeout=3 if cancel else 0.15)
        assert caught.value.code == ("model_cancelled" if cancel else "model_timeout")
    finally:
        if timer:
            timer.join()
    assert time.monotonic() - started < 3
    assert processes and processes[0].poll() is not None
    assert sorted(p.name for p in job.iterdir()) == ["source.bin"]


def test_pre_cancel_never_spawns(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    event = threading.Event()
    event.set()
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: pytest.fail("spawned cancelled job"))
    with pytest.raises(ModelImportError, match="cancelled"):
        runner.run_inspect(job, DEPENDENCIES, cancel_event=event)


def test_async_task_cancellation_joins_the_runner(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    substitute_worker(tmp_path, monkeypatch, "import time\ntime.sleep(30)\n")
    event = threading.Event()

    async def run():
        future = asyncio.create_task(runner.run_inspect_async(job, DEPENDENCIES, cancel_event=event))
        await asyncio.sleep(0.15)
        future.cancel()
        with pytest.raises(asyncio.CancelledError):
            await future
        assert event.is_set()

    asyncio.run(run())
    assert sorted(p.name for p in job.iterdir()) == ["source.bin"]


def test_result_schema_sizes_and_hashes(tmp_path):
    job = make_job(tmp_path)
    task.execute_inspect(job)
    original = (job / "summary.json").read_bytes()
    (job / "summary.json").write_bytes(b" " * (48 * 1024 + 1))
    with pytest.raises(ModelImportError):
        runner._result(job)
    (job / "summary.json").write_bytes(original)
    (job / "cache.json").write_bytes(b"{}")
    with pytest.raises(ModelImportError):
        runner._result(job)
    with pytest.raises(ModelImportError, match="cache"):
        cache.load_cache(job)


@pytest.mark.parametrize("change", [
    {"schemaVersion": True}, {"triangles": -1}, {"partsTotal": 5000}, {"rawSize": {"width": float("nan")}},
    {"sourceSha256": "../escape"}, {"name": "\x00"}, {"nextPartsOffset": 999},
])
def test_summary_schema_rejects_invalid_worker_values(tmp_path, change):
    job = make_job(tmp_path)
    summary = task.execute_inspect(job)
    summary.update(change)
    with pytest.raises(ModelImportError):
        protocol.validate_summary(summary)


def test_existing_outputs_are_not_overwritten(tmp_path):
    job = make_job(tmp_path)
    (job / "summary.json").write_bytes(b"existing")
    with pytest.raises(ModelImportError):
        runner.run_inspect(job, DEPENDENCIES)
    assert (job / "summary.json").read_bytes() == b"existing"


def test_source_reads_remain_inside_job(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    reads = []
    original = Path.open

    def tracked(self, mode="r", *args, **kwargs):
        if "r" in mode:
            reads.append(self.resolve())
        return original(self, mode, *args, **kwargs)

    monkeypatch.setattr(Path, "open", tracked)
    task.execute_inspect(job)
    assert reads and all(p.parent == job.resolve() for p in reads)


def test_environment_is_allowlisted(tmp_path, monkeypatch):
    monkeypatch.setenv("MODEL_IMPORT_SYNTHETIC_SECRET", "must-not-pass")
    monkeypatch.setenv("PYTHONPATH", str(tmp_path / "poison"))
    environment = runner.worker_environment(tmp_path, sys.executable)
    assert "MODEL_IMPORT_SYNTHETIC_SECRET" not in environment and "PYTHONPATH" not in environment
    assert environment["HOME"] == environment["TEMP"] == str(tmp_path)
    assert environment["OPENBLAS_NUM_THREADS"] == "1"
    assert set(environment) <= {"HOME", "USERPROFILE", "TMP", "TEMP", "TMPDIR", "APPDATA", "LOCALAPPDATA",
                                "PATH", "OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS",
                                "NUMEXPR_NUM_THREADS", "SYSTEMROOT", "WINDIR"}


def test_real_bootstrap_ignores_cwd_pth_and_inherited_environment(tmp_path, monkeypatch):
    job = make_job(tmp_path)
    dependencies = tmp_path / "probe-dependencies"
    dependencies.mkdir()
    poison = "raise RuntimeError('startup hook must not execute')\n"
    (dependencies / "poison.pth").write_bytes(b"import missing_forbidden_hook\n")
    for name in ("sitecustomize.py", "usercustomize.py"):
        (dependencies / name).write_bytes(poison.encode())
    (job / "numpy.py").write_bytes(poison.encode())
    # A host-owned synthetic dependency audits startup before raising a missing dependency.
    (dependencies / "numpy.py").write_bytes(
        ("import json,os,sys\nfrom pathlib import Path\n"
         "Path('probe.json').write_text(json.dumps({'isolated':sys.flags.isolated,'no_site':sys.flags.no_site,"
         "'bytecode':sys.dont_write_bytecode,'paths':sys.path,'cwd':str(Path.cwd()),"
         "'leaked':[k for k in os.environ if k.startswith(('PYTHON','MODEL_IMPORT_'))],"
         "'appImported':any(k=='ai_inspector' or k.startswith('ai_inspector.') for k in sys.modules)}))\n"
         "raise ImportError('probe complete')\n").encode())
    monkeypatch.setenv("PYTHONPATH", str(job))
    monkeypatch.setenv("MODEL_IMPORT_SYNTHETIC_SECRET", "synthetic")
    with pytest.raises(ModelImportError) as caught:
        runner.run_inspect(job, dependencies)
    assert caught.value.code == "model_runtime_unavailable"
    probe = json.loads((job / "probe.json").read_bytes())
    assert probe["isolated"] == probe["no_site"] == 1 and probe["bytecode"]
    assert probe["cwd"] not in probe["paths"] and "" not in probe["paths"]
    assert probe["leaked"] == [] and probe["appImported"] is False


def test_package_imports_only_stdlib_numpy_pillow_and_relative_modules():
    allowed = sys.stdlib_module_names | {"numpy", "PIL"}
    for file in PACKAGE.glob("*.py"):
        for node in ast.walk(ast.parse(file.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                roots = [alias.name.split(".")[0] for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level:
                roots = [(node.module or "").split(".")[0]]
            else:
                continue
            assert set(roots) <= allowed, (file.name, roots)
            assert not set(roots) & {"socket", "http", "urllib"}, (file.name, roots)


@pytest.mark.skipif(os.name == "nt", reason="POSIX resource module")
def test_posix_limits_include_address_space_and_file_descriptors(monkeypatch):
    import resource
    calls = []
    monkeypatch.setattr(resource, "getrlimit", lambda kind: (resource.RLIM_INFINITY, resource.RLIM_INFINITY))
    monkeypatch.setattr(resource, "setrlimit", lambda kind, value: calls.append((kind, value)))
    assert worker.limit_resources()
    assert (resource.RLIMIT_AS, (1536 * 1024 * 1024,) * 2) in calls
    assert (resource.RLIMIT_NOFILE, (64, 64)) in calls
    assert (resource.RLIMIT_CPU, (60, 60)) in calls
    assert (resource.RLIMIT_CORE, (0, 0)) in calls


WINDOWS_LIMIT_PROBE = """import ctypes,json
from ctypes import wintypes
from pathlib import Path
class Basic(ctypes.Structure):
    _fields_ = [('process_time',ctypes.c_int64),('job_time',ctypes.c_int64),('flags',wintypes.DWORD),
                ('min_ws',ctypes.c_size_t),('max_ws',ctypes.c_size_t),('processes',wintypes.DWORD),
                ('affinity',ctypes.c_size_t),('priority',wintypes.DWORD),('scheduling',wintypes.DWORD)]
class IO(ctypes.Structure):
    _fields_ = [(key,ctypes.c_uint64) for key in ('a','b','c','d','e','f')]
class Extended(ctypes.Structure):
    _fields_ = [('basic',Basic),('io',IO),('process_memory',ctypes.c_size_t),('job_memory',ctypes.c_size_t),
                ('peak_process',ctypes.c_size_t),('peak_job',ctypes.c_size_t)]
kernel = ctypes.WinDLL('kernel32',use_last_error=True)
kernel.QueryInformationJobObject.argtypes = (wintypes.HANDLE,ctypes.c_int,ctypes.c_void_p,wintypes.DWORD,ctypes.c_void_p)
kernel.QueryInformationJobObject.restype = wintypes.BOOL
info = Extended()
ok = kernel.QueryInformationJobObject(None,9,ctypes.byref(info),ctypes.sizeof(info),None)
Path('probe.json').write_text(json.dumps({'ok':bool(ok),'flags':info.basic.flags,
                                        'cpu':info.basic.process_time,'processes':info.basic.processes,
                                        'memory':info.process_memory}))
raise ImportError('probe complete')
"""


@pytest.mark.skipif(os.name != "nt", reason="Windows Job Object")
def test_real_worker_enables_windows_job_limits_before_import(tmp_path):
    job = make_job(tmp_path)
    dependencies = tmp_path / "probe-dependencies"
    dependencies.mkdir()
    (dependencies / "numpy.py").write_bytes(WINDOWS_LIMIT_PROBE.encode("ascii"))
    with pytest.raises(ModelImportError) as caught:
        runner.run_inspect(job, dependencies)
    assert caught.value.code == "model_runtime_unavailable"
    value = json.loads((job / "probe.json").read_bytes())
    assert value["ok"] and value["flags"] & 0x210A == 0x210A
    assert value["cpu"] == 60 * 10_000_000 and value["processes"] == 1
    assert value["memory"] == 1536 * 1024 * 1024


def test_posix_limit_set_failure_is_closed(monkeypatch):
    if os.name == "nt":
        pytest.skip("POSIX resource module")
    import resource

    def unavailable(*args):
        raise OSError("limit unavailable")

    monkeypatch.setattr(resource, "setrlimit", unavailable)
    assert worker.limit_resources() is False
