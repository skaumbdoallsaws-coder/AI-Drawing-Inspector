"""Windows path length (2026-11-09): the desktop keeps its data under a long OneDrive folder, and with 64 + 32
character folder names every prepare job crossed Windows' 259-character limit and failed as "model worker failed".
The store now uses 24 + 16 character names and refuses clearly when its deepest job path would still be too long."""
import os
from pathlib import Path
import time

import pytest

from ai_inspector.facility_layout import model_import_store as module
from ai_inspector.facility_layout.errors import FacilityLayoutError
from tests.model_import_store_support import layout_reader, recipe, scope, wait


def padded_root(tmp_path: Path, length: int) -> Path:
    """A layout root whose store folder (root / model-imports) is exactly `length` characters long."""
    base = len(str(tmp_path)) + 1 + len(module.STORE_FOLDER) + 1
    assert length - base >= 1, "the temporary folder is already too long for this test"
    return tmp_path / ("p" * (length - base))


def test_folder_names_are_short():
    assert module.SCOPE_KEY.fullmatch(scope().key)
    assert len(scope().key) == 24 and len(module.uuid.uuid4().hex[:16]) == 16


@pytest.mark.skipif(os.name != "nt", reason="Windows path limit")
def test_store_at_the_deepest_allowed_path_uploads_and_prepares_with_the_real_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_long_paths_enabled", lambda: False)
    from tests.model_import_test_support import textured_box
    root = padded_root(tmp_path, module.WINDOWS_MAX_PATH - module.DEEPEST_BELOW_STORE)
    instance = module.ModelImportStore(root, layout_reader=layout_reader)
    assert len(str(instance.root)) + module.DEEPEST_BELOW_STORE == module.WINDOWS_MAX_PATH
    incoming = instance.begin_upload(scope(), "box.glb")
    incoming.write(textured_box().bytes())
    record = incoming.finish()
    deadline = time.monotonic() + 70
    while time.monotonic() < deadline:
        record = instance.get(scope(), record["id"])
        if record["state"] not in ("queued", "checking"):
            break
        time.sleep(.05)
    assert record["state"] == "ready", record
    wait(instance, scope(), record["id"])
    draft = instance.prepare(scope(), recipe(record["id"]))
    assert instance.preview(scope(), draft["draftId"], draft=True).startswith(b"\x89PNG")


@pytest.mark.skipif(os.name != "nt", reason="Windows path limit")
def test_one_character_deeper_is_refused_clearly_before_any_worker(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_long_paths_enabled", lambda: False)
    root = padded_root(tmp_path, module.WINDOWS_MAX_PATH - module.DEEPEST_BELOW_STORE + 1)
    instance = module.ModelImportStore(root, layout_reader=layout_reader)
    with pytest.raises(FacilityLayoutError) as caught:
        instance.begin_upload(scope(), "box.glb", 8)
    assert caught.value.code == "model_store_path_too_long" and caught.value.status_code == 507
    assert "too long for Windows" in str(caught.value)
    assert not (instance.root / "active").exists() or not any((instance.root / "active").iterdir())


def test_long_paths_turned_on_lifts_the_limit(tmp_path, monkeypatch):
    monkeypatch.setattr(module, "_long_paths_enabled", lambda: True)
    module.require_path_budget(tmp_path / ("p" * 300))
