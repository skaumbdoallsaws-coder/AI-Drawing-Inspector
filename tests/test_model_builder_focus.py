"""Contained focus worker and scoped cache. Run outside the low-memory sandbox."""
from hashlib import sha256
from pathlib import Path

import numpy as np
import pytest

from ai_inspector.facility_layout import model_build_views
from ai_inspector.facility_layout.errors import FacilityLayoutError
from ai_inspector.industrial_assets import model_builder_runner as runner
from ai_inspector.industrial_assets.model_builder_bundle import FOLDER
from tests.model_builder_draft_support import build, store
from tests.model_builder_test_support import module, reference
from tests.model_import_store_support import PNG, scope

DEPENDENCIES = Path(np.__file__).resolve().parent.parent


def test_focus_worker_rerenders_the_pinned_model_with_byte_parity(tmp_path):
    built = module("build").build_model(reference("pack-station-printer"))
    restored = module("imports").module("reader").read_model(built.glb, extended_materials=True)
    parts = [{"index": i, "name": part.name} for i, part in enumerate(restored.parts)
             if part.name == "scale display"]
    assert parts
    job = tmp_path / "focus"
    job.mkdir()
    worker = runner.run_focus(job, DEPENDENCIES, built.glb, parts)
    expected = module("pictures").render_previews(restored, appearance_colors=runner.appearance_colors(),
                                                   focus_indices=[part["index"] for part in parts], thumbnail=False)
    assert worker == expected.preview
    assert {p.name for p in job.iterdir()} == {"model.glb", runner.job_io.FOCUS_REQUEST,
                                              runner.job_io.APPEARANCE_COLORS, "preview.png"}


def test_focus_cache_reuses_picture_and_reloads_registered_artifact(tmp_path, monkeypatch):
    site, bound = store(tmp_path), scope()
    result = build(site, bound)
    draft_id = result["draftId"]
    draft = site.draft(bound, draft_id)
    key = result["parts"][0]["key"]
    project = tmp_path / "project"
    calls = []
    def fake_focus(job, dependencies, payload, parts, **kwargs):
        calls.append((sha256(payload).hexdigest(), parts))
        return PNG
    monkeypatch.setattr(model_build_views, "run_focus", fake_focus)
    assert site.focus_build_view(bound, draft_id, key, project) == PNG
    assert site.focus_build_view(bound, draft_id, key, project) == PNG
    assert site.focus_build_view(bound, draft_id, "body", project) == PNG
    assert len(calls) == 1
    artifact = project / FOLDER / draft["assetId"] / "model.glb"
    artifact.parent.mkdir(parents=True)
    frozen = site._folder(bound) / "drafts" / draft_id / "model.glb"
    artifact.write_bytes(frozen.read_bytes())
    with site.hold_draft(bound, draft_id) as (_, _, lease):
        site.record_receipt(bound, draft_id, draft["assetId"], "revision", _lease=lease)
    assert not frozen.exists()
    cache = site._folder(bound) / "views" / draft_id
    for picture in cache.glob("*.png"):
        picture.unlink()
    assert site.focus_build_view(bound, draft_id, key, project) == PNG
    assert len(calls) == 2 and calls[0][0] == calls[1][0] == draft["outputSha256"]


def test_focus_rejects_missing_part_and_wrong_scope(tmp_path, monkeypatch):
    site, bound = store(tmp_path), scope()
    result = build(site, bound)
    with pytest.raises(FacilityLayoutError) as caught:
        site.focus_build_view(bound, result["draftId"], "unknown part", tmp_path)
    assert caught.value.code == "model_focus_invalid"
    with pytest.raises(FacilityLayoutError):
        site.focus_build_view(scope(site="other"), result["draftId"], result["parts"][0]["key"], tmp_path)
