"""MB4a opt-in previews inside the existing contained build worker. Run outside sandbox."""
from pathlib import Path
import threading

import numpy as np
import pytest

from ai_inspector.industrial_assets import model_builder_runner as runner
from ai_inspector.industrial_assets.model_builder import drafts
from tests.model_builder_test_support import module, recipe, shape

DEPENDENCIES = Path(np.__file__).resolve().parent.parent


def test_real_worker_builds_complete_draft_with_existing_print_preview_renderer(tmp_path):
    raw = recipe(shape("panel", center=[0, .1, 0], size=[.3, .2],
                       print={"background": "#ffffff", "items": [
                           {"text": "OUTBOUND", "box": [.05, .1, .95, .8], "color": "#000000"}]}),
                 size={"width": .3, "height": .2, "depth": .0025})
    expected = module("build").build_model(raw)
    destination = tmp_path / "built"
    frozen = runner.prepare_build_draft(raw, destination, threading.Event(), dependency_root=DEPENDENCIES,
        categories=[raw["category"]], appearance_ids=[], scope="a"*24, created=1700000000)
    assert drafts.read_draft(destination) == frozen
    assert (destination / "model.glb").read_bytes() == expected.glb
    # Same renderer/read mode, no new shader or special MB4b camera path.
    imports = module("imports").module
    restored = imports("reader").read_model(expected.glb, extended_materials=True)
    assert any(m.get("artwork") and m["texture"] for m in restored.materials)
    pictures = imports("preview").render_previews(restored)
    assert (destination / "preview.png").read_bytes() == pictures.preview
    assert (destination / "thumbnail.webp").read_bytes() == pictures.thumbnail
    assert frozen["kind"] == "build"


@pytest.mark.parametrize("failure", ["missing", "corrupt", "cancelled"])
def test_runner_refuses_partial_preview_outputs_and_cleans_only_owned_outputs(tmp_path, monkeypatch, failure):
    job = tmp_path / "job"
    job.mkdir()
    raw = recipe()
    runner.write_job_inputs(job, raw, categories=[raw["category"]], appearance_ids=[], previews=True)
    cancel = threading.Event()
    launch = runner.launch._launch
    def changed(*args, **kwargs):
        launch(*args, **kwargs)
        if failure == "missing":
            (job / "thumbnail.webp").unlink()
        elif failure == "corrupt":
            (job / "preview.png").write_bytes(b"corrupt")
        else:
            cancel.set()
    monkeypatch.setattr(runner.launch, "_launch", changed)
    with pytest.raises(runner.ModelImportError) as caught:
        runner.run_build(job, DEPENDENCIES, cancel_event=cancel)
    assert caught.value.code == ("model_cancelled" if failure == "cancelled" else "model_worker_failed")
    assert not any((job / name).exists() for name in runner.job_io.OUTPUT_NAMES)
    assert {p.name for p in job.iterdir()} == runner.job_io.INPUT_NAMES | {runner.job_io.PREVIEW_REQUEST}
