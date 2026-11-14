"""Disposable native-gate preparation contracts; no app/dependencies/real inputs."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("documentation_editor_prepare", ROOT / "desktop/tools/documentation-editor-prepare.py")
PREPARE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREPARE)


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    from tools import documentation_baseline
    source, root = tmp_path / "source", tmp_path / "snapshot"
    source.mkdir()
    root.mkdir()
    (root / "desktop-checkpoint.json").write_text(json.dumps({"schemaVersion": 1, "source": str(source)}))
    (root / "desktop-source-manifest.json").write_text("[]")
    names = ["docs/operations-manual/source-register.json", "400S_Sorted_Library/part_number_registry.json"]
    seeds = ["generated/parts_manual/mmle-50d/" + name for name in ("manual-plan.json", "documentation-scene.json")]
    for name in names + seeds:
        file = source / name
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b'{"synthetic": true}\n')
    monkeypatch.setattr(documentation_baseline, "local_inventory", lambda _root: {
        "available": True, "missingInputs": [], "inputFiles": names})
    return root, source, root / ".runtime" / "gate", names, seeds


def test_preparation_writes_only_disposable_profile_and_allowlisted_inputs(fixture):
    root, source, output, names, seeds = fixture
    before = {name: (source / name).read_bytes() for name in names + seeds}
    result = PREPARE.prepare(root, output, source)
    profile = json.loads(Path(result["profile"]).read_bytes())
    marker = json.loads((Path(profile["dataRoot"]) / "documentation-editor-check.json").read_bytes())
    assert marker["disposable"] is True
    assert profile["mode"] == "application" and profile["startupLayoutId"] is None
    assert profile["origin"].startswith("http://127.0.0.1:") and not profile["origin"].endswith(":8480")
    assert set(marker["stores"]) == set(PREPARE.ROOTS)
    for value in [profile[k] for k in ("dataRoot", "facilityRoot", "libraryRoot")] + list(marker["stores"].values()):
        assert Path(value).is_relative_to(output)
    assert not {"modelGateway", "codexRuntime", "packagingRuntime"} & profile.keys()
    assert (Path(profile["libraryRoot"]) / "part_number_registry.json").is_file()
    assert (Path(marker["stores"]["PARTS_MANUAL_ROOT"]) / "mmle-50d/documentation-scene.json").read_bytes() == before[seeds[1]]
    assert before == {name: (source / name).read_bytes() for name in names + seeds}
    assert all(item["sha256"] and item["bytes"] for item in marker["inputs"])
    assert not (output / "e/report.json").exists()  # Preparation never claims a native pass.


def test_existing_unmarked_output_is_never_adopted_or_overwritten(fixture):
    root, source, output, *_ = fixture
    output.mkdir(parents=True)
    sentinel = output / "not-disposable.txt"
    sentinel.write_bytes(b"keep")
    with pytest.raises(ValueError, match="new output folder"):
        PREPARE.prepare(root, output, source)
    assert sentinel.read_bytes() == b"keep"
    assert not (output / "profile.json").exists()


def test_preparation_refuses_store_outside_snapshot_output(fixture):
    root, source, output, *_ = fixture
    with pytest.raises(ValueError, match="below the snapshot"):
        PREPARE.prepare(root, source / "stores", source)
    assert not (source / "stores").exists()
    with pytest.raises(ValueError, match="below the snapshot"):
        PREPARE.prepare(root, root / ".runtime", source)


@pytest.mark.parametrize("damage", ["git", "marker", "overlap", "manifest"])
def test_preparation_refuses_live_or_incomplete_code_root(fixture, damage):
    root, source, output, *_ = fixture
    if damage == "git":
        (root / ".git").mkdir()
    elif damage == "marker":
        (root / "desktop-checkpoint.json").unlink()
    elif damage == "manifest":
        (root / "desktop-source-manifest.json").unlink()
    else:
        (root / "desktop-checkpoint.json").write_text(json.dumps({"schemaVersion": 1, "source": str(root)}))
    with pytest.raises(ValueError):
        PREPARE.prepare(root, output, source)
    assert not output.exists()


def test_missing_engineering_inputs_fail_before_profile_creation(fixture, monkeypatch):
    from tools import documentation_baseline
    root, source, output, *_ = fixture
    monkeypatch.setattr(documentation_baseline, "local_inventory", lambda _: {
        "available": False, "missingInputs": ["model.glb"], "inputFiles": []})
    with pytest.raises(ValueError, match="Required MMLE inputs absent"):
        PREPARE.prepare(root, output, source)
    assert not output.exists()


def test_absolute_paths_and_existing_dependency_folders_are_required(fixture):
    root, source, output, *_ = fixture
    with pytest.raises(ValueError, match="absolute local"):
        PREPARE.prepare(root, Path("relative"), source)
    with pytest.raises(ValueError, match="Dependency folders"):
        PREPARE.prepare(root, output, source, [source / "absent-dependencies"])
    assert not output.exists()


def test_dependency_folders_are_recorded_without_copying_packages(fixture):
    root, source, output, *_ = fixture
    dependency = source / "deps"
    dependency.mkdir()
    PREPARE.prepare(root, output, source, [dependency])
    marker = json.loads((output / "d/documentation-editor-check.json").read_bytes())
    assert marker["dependencies"] == [str(dependency)]
    assert list(dependency.iterdir()) == []
    assert not (output / "node_modules").exists()
