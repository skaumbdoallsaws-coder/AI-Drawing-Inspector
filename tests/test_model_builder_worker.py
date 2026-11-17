"""Numerical worker/host integration; run separately on the configured test venv."""
import asyncio
from pathlib import Path
import subprocess
import threading

import numpy as np
import pytest

from ai_inspector.industrial_assets import model_builder_runner as host
from tests.model_builder_test_support import include, module, recipe, reference
from tests.test_model_builder_protocol import recipe_60001

DEPENDENCIES = Path(np.__file__).resolve().parent.parent
kernel = module("build")


def job(tmp_path, raw=None):
    directory = tmp_path / "job"
    directory.mkdir()
    value = reference("carrier-tag-ups") if raw is None else raw
    normalized = host.write_job_inputs(directory, value, categories=[value["category"]], appearance_ids=[])
    return directory, normalized


def input_snapshot(directory):
    return {str(p.relative_to(directory)): p.read_bytes() for p in directory.rglob("*") if p.is_file()}


@pytest.mark.parametrize("name", ["carrier-tag-ups", "baler-vertical-42", "gaylord-on-pallet",
                                  "pack-station-printer", "pallet-plain", "roll-cage-plain"])
def test_real_worker_matches_kernel_and_host_verifies_hang_height(tmp_path, monkeypatch, name):
    raw = reference(name)
    directory, normalized = job(tmp_path, raw)
    expected = kernel.build_model(raw)
    original = host.primitives.verify
    verified = []
    def verify(payload, dimensions, *, base_height=0):
        verified.append((dimensions, base_height))
        return original(payload, dimensions, base_height=base_height)
    monkeypatch.setattr(host.primitives, "verify", verify)
    result = host.run_build(directory, DEPENDENCIES)
    assert (directory / "model.glb").read_bytes() == expected.glb
    assert result["dimensions"] == expected.dimensions
    assert result["catalogDimensions"] == expected.catalog_dimensions
    assert result["partMap"] == expected.part_map
    assert result["lints"] == []
    assert result["budgets"] == expected.budgets
    assert result["provenance"] == expected.provenance
    assert verified == [(result["dimensions"], normalized["hangHeight"])]
    assert (directory / "result.json").stat().st_size <= host.protocol.RESULT_BYTES
    assert {p.name for p in directory.iterdir()} == host.job_io.INPUT_NAMES | {"model.glb", "result.json"}
    assert not list(directory.rglob("*.pyc"))


@pytest.mark.parametrize("case,code,path", [
    ("schema", "schema_invalid", "$.entries[0].unknown"),
    ("complexity", "budget_exceeded", "$.entries[2]"),
    ("include", "include_missing", "$.includes"),
    ("font", "font_missing", "$.fonts")])
def test_host_decodes_real_refusal_and_cleans_only_outputs(tmp_path, case, code, path):
    directory, raw = job(tmp_path, recipe())
    if case == "schema":
        raw["entries"][0]["unknown"] = "invalid"
    elif case == "complexity":
        raw = recipe_60001()
    elif case == "include":
        raw = host.normalize_recipe(recipe(include()))
    if case == "font":
        font = directory / "fonts/Aileron-Regular-subset.ttf"
        data = bytearray(font.read_bytes())
        data[-1] ^= 1
        font.write_bytes(data)
    else:
        (directory / "recipe.json").write_bytes(host.json_bytes(raw))
    before = input_snapshot(directory)
    with pytest.raises(host.ModelBuildError) as caught:
        host.run_build(directory, DEPENDENCIES)
    assert caught.value.code == code and caught.value.path == path
    if case == "complexity":
        assert caught.value.to_dict()["details"]["triangles"] == 60001
        assert caught.value.to_dict()["details"]["limit"] == 60000
    assert input_snapshot(directory) == before


def test_missing_dependency_is_a_runtime_refusal(tmp_path):
    directory, _ = job(tmp_path)
    empty = tmp_path / "empty"
    empty.mkdir()
    with pytest.raises(host.ModelImportError) as caught:
        host.run_build(directory, empty)
    assert caught.value.code == "model_runtime_unavailable"
    assert not any((directory / name).exists() for name in host.job_io.OUTPUT_NAMES)


def test_preexisting_output_and_precancel_are_preserved_without_launch(tmp_path, monkeypatch):
    directory, _ = job(tmp_path)
    monkeypatch.setattr(host.launch, "_launch", lambda *a, **k: pytest.fail("unexpected launch"))
    (directory / "model.glb").write_bytes(b"preexisting")
    with pytest.raises(host.ModelImportError):
        host.run_build(directory, DEPENDENCIES)
    assert (directory / "model.glb").read_bytes() == b"preexisting"
    event = threading.Event()
    event.set()
    with pytest.raises(host.ModelImportError) as caught:
        host.run_build(directory, DEPENDENCIES, cancel_event=event)
    assert caught.value.code == "model_cancelled"
    assert (directory / "model.glb").read_bytes() == b"preexisting"


@pytest.mark.parametrize("cancel", [False, True])
def test_host_cancellation_timeout_kill_and_join_and_remove_partial_outputs(tmp_path, monkeypatch, cancel):
    directory, _ = job(tmp_path)
    before = input_snapshot(directory)
    stub = tmp_path / "sleep_worker.py"
    stub.write_text("from pathlib import Path\nimport time\nPath('model.glb').write_bytes(b'partial')\ntime.sleep(30)\n")
    monkeypatch.setattr(host.launch, "_WORKER", stub)
    processes = []
    original = subprocess.Popen
    def capture(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        if timer:
            timer.start()
        return process
    monkeypatch.setattr(host.launch.subprocess, "Popen", capture)
    event = threading.Event()
    timer = threading.Timer(.2, event.set) if cancel else None
    try:
        with pytest.raises(host.ModelImportError) as caught:
            host.run_build(directory, DEPENDENCIES, cancel_event=event, timeout=5 if cancel else .2)
        assert caught.value.code == ("model_cancelled" if cancel else "model_timeout")
    finally:
        if timer and timer.ident is not None:
            timer.join()
    assert processes and processes[0].poll() is not None
    assert input_snapshot(directory) == before


def test_async_cancel_cleans_a_completed_but_undelivered_result(tmp_path, monkeypatch):
    directory, _ = job(tmp_path)
    before = input_snapshot(directory)
    completed, release = threading.Event(), threading.Event()
    original = host.run_build
    def held(*args, **kwargs):
        value = original(*args, **kwargs)
        completed.set()
        release.wait(10)
        return value
    monkeypatch.setattr(host, "run_build", held)
    async def run():
        future = asyncio.create_task(host.run_build_async(directory, DEPENDENCIES))
        ready = await asyncio.to_thread(completed.wait, 10)
        assert ready
        future.cancel()
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await future
    try:
        asyncio.run(run())
    finally:
        release.set()
    assert input_snapshot(directory) == before


def test_host_verification_is_required_before_return_and_failure_cleans(tmp_path, monkeypatch):
    directory, _ = job(tmp_path)
    before = input_snapshot(directory)
    calls = []
    def invalid(*args, **kwargs):
        calls.append(kwargs)
        raise ValueError("Generic geometry verification failure")
    monkeypatch.setattr(host.primitives, "verify", invalid)
    with pytest.raises(host.ModelImportError) as caught:
        host.run_build(directory, DEPENDENCIES)
    assert caught.value.code == "model_worker_failed"
    assert calls == [{"base_height": .635}]
    assert input_snapshot(directory) == before


@pytest.mark.parametrize("tamper", ["glb", "summary", "map", "input", "material"])
def test_host_rejects_tampered_or_inconsistent_output(tmp_path, monkeypatch, tamper):
    import json
    directory, _ = job(tmp_path)
    original = host.launch._launch
    def changed(*args, **kwargs):
        original(*args, **kwargs)
        summary = json.loads((directory / "result.json").read_bytes())
        if tamper == "glb":
            (directory / "model.glb").write_bytes(b"invalid GLB")
        elif tamper == "summary":
            summary["catalogDimensions"]["height"] += 1
        elif tamper == "map":
            summary["partMap"]["instances"]["invented[0]"] = [summary["parts"][0]["key"]]
        elif tamper == "input":
            data = (directory / "allowed.json").read_bytes()
            (directory / "allowed.json").write_bytes(data + b"\n")
        else:
            # Keep hash, geometry and part metadata internally plausible; material binding must still reject.
            summary["materials"][0]["roughness"] = .123
        (directory / "result.json").write_bytes(host.json_bytes(summary))
    monkeypatch.setattr(host.launch, "_launch", changed)
    with pytest.raises(host.ModelImportError) as caught:
        host.run_build(directory, DEPENDENCIES)
    assert caught.value.code == "model_worker_failed"
    assert not any((directory / name).exists() for name in host.job_io.OUTPUT_NAMES)


def test_input_writer_does_not_overwrite_existing_input_or_trust_recipe_paths(tmp_path):
    directory, _ = job(tmp_path)
    before = input_snapshot(directory)
    with pytest.raises(host.ModelBuildError):
        host.write_job_inputs(directory, recipe(), categories=["Material Handling"], appearance_ids=[])
    assert input_snapshot(directory) == before
    empty = tmp_path / "new-job"
    empty.mkdir()
    with pytest.raises(host.ModelBuildError):
        host.write_job_inputs(empty, recipe(font_directory="../elsewhere"),
                              categories=["Material Handling"], appearance_ids=[])
    assert list(empty.iterdir()) == []
