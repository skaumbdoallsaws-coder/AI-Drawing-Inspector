"""Process lifetime regressions, including Windows venv launchers and child trees."""
import os
from pathlib import Path
import subprocess
import sys
import threading
import time

import pytest

from tests.model_import_test_support import module

runner = module("runner")
host = module("prepare_runner")
tree_module = module("process_tree")
cleanup = module("cleanup")
ModelImportError = module("errors").ModelImportError


def test_base_interpreter_is_used_with_isolated_flags(tmp_path, monkeypatch):
    base = tree_module.base_executable()
    monkeypatch.setattr(sys, "executable", str(tmp_path / "venv-launcher.exe"))
    monkeypatch.setattr(sys, "_base_executable", base)
    stub = tmp_path / "stub.py"
    stub.write_bytes(b"raise SystemExit(3)\n")
    monkeypatch.setattr(runner, "_WORKER", stub)
    seen, original = [], subprocess.Popen
    def capture(*args, **kwargs):
        seen.append((args, kwargs))
        return original(*args, **kwargs)
    monkeypatch.setattr(runner.subprocess, "Popen", capture)
    with pytest.raises(ModelImportError) as caught:
        runner._launch(tmp_path, tmp_path, "inspect", threading.Event(), 3)
    assert caught.value.code == "model_runtime_unavailable"
    assert seen[0][0][0][:4] == [base, "-I", "-S", "-B"]
    assert seen[0][1]["start_new_session"] is (os.name != "nt")
    assert seen[0][1]["env"]["PATH"].split(os.pathsep)[0] == str(Path(base).parent)


@pytest.mark.parametrize("value", ["relative.exe", None, "Z:/missing-model-python.exe"])
def test_base_interpreter_must_be_absolute_and_exist(monkeypatch, value):
    monkeypatch.setattr(sys, "_base_executable", value)
    with pytest.raises(ModelImportError) as caught:
        tree_module.base_executable()
    assert caught.value.code == "model_runtime_unavailable"


@pytest.mark.parametrize("task", ["inspect", "prepare"])
@pytest.mark.parametrize("cancel", [False, True])
def test_timeout_cancel_kills_descendants_and_releases_job_directory(tmp_path, monkeypatch, task, cancel):
    job = tmp_path / "job"
    job.mkdir()
    child = tmp_path / "child.py"
    child.write_bytes(b"import time\nfrom pathlib import Path\nPath('child-ready').write_text('ready')\n"
                      b"while True:\n Path('heartbeat').write_text(str(time.monotonic()))\n time.sleep(.02)\n")
    worker = tmp_path / "stub.py"
    worker.write_bytes(("import subprocess,sys,time\n"
                        "subprocess.Popen([sys.executable, '-I', '-S', '-B', " + repr(str(child)) + "],"
                        "creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))\n"
                        "time.sleep(30)\n").encode())
    monkeypatch.setattr(runner, "_WORKER", worker)
    event = threading.Event()
    timer = threading.Timer(.7, event.set) if cancel else None
    if timer:
        timer.start()
    try:
        with pytest.raises(ModelImportError) as caught:
            runner._launch(job, tmp_path, task, event, 5 if cancel else .7)
        assert caught.value.code == ("model_cancelled" if cancel else "model_timeout")
    finally:
        if timer:
            timer.join()
    assert (job / "child-ready").is_file(), "the descendant must actually have started"
    heartbeat = (job / "heartbeat").read_bytes()
    time.sleep(.1)
    assert (job / "heartbeat").read_bytes() == heartbeat
    # A live descendant with cwd=job prevents this on Windows.
    assert cleanup.retry_cleanup(lambda: job.rename(tmp_path / "released"))


@pytest.mark.parametrize("code", ["model_timeout", "model_cancelled"])
def test_cleanup_failure_does_not_replace_original_refusal(tmp_path, monkeypatch, code):
    source = tmp_path / "source.bin"
    source.write_bytes(b"source")
    monkeypatch.setattr(host, "_launch", lambda *a: (_ for _ in ()).throw(ModelImportError(code)))
    attempts = []
    def locked(path):
        attempts.append(path)
        raise PermissionError("simulated delayed Windows handle release")
    monkeypatch.setattr(cleanup.shutil, "rmtree", locked)
    with pytest.raises(ModelImportError) as caught:
        host.prepare_draft(source, {"importId": "mi-" + "0" * 24, "name": "Test", "category": "decor"},
                           tmp_path / "draft", dependency_root=tmp_path)
    assert caught.value.code == code
    assert len(attempts) == 5 and len(list(tmp_path.glob(".model-prepare-*"))) == 1
    assert not (tmp_path / "draft").exists()


def test_cleanup_retries_transient_locks():
    calls = []
    def action():
        calls.append(1)
        if len(calls) < 3:
            raise PermissionError("temporarily locked")
    assert cleanup.retry_cleanup(action) and len(calls) == 3


def test_containment_setup_failure_never_launches_worker(tmp_path, monkeypatch):
    def unavailable():
        raise ModelImportError("model_limits_unavailable")
    monkeypatch.setattr(runner, "ProcessTree", unavailable)
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **k: pytest.fail("must fail before spawn"))
    with pytest.raises(ModelImportError) as caught:
        runner._launch(tmp_path, tmp_path, "inspect", threading.Event(), 3)
    assert caught.value.code == "model_limits_unavailable"


def test_containment_assignment_failure_still_kills_and_joins(tmp_path, monkeypatch):
    original = tree_module.ProcessTree
    stopped = []
    class RefuseAssignment(original):
        def attach(self, process):
            super().attach(process)
            raise ModelImportError("model_limits_unavailable")
        def stop(self, process):
            super().stop(process)
            stopped.append(process.returncode)
    worker = tmp_path / "stub.py"
    worker.write_bytes(b"import time\ntime.sleep(30)\n")
    monkeypatch.setattr(runner, "_WORKER", worker)
    monkeypatch.setattr(runner, "ProcessTree", RefuseAssignment)
    with pytest.raises(ModelImportError) as caught:
        runner._launch(tmp_path, tmp_path, "prepare", threading.Event(), 3)
    assert caught.value.code == "model_limits_unavailable"
    assert len(stopped) == 1 and stopped[0] is not None
