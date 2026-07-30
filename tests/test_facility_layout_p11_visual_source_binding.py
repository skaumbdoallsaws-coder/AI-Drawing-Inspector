from __future__ import annotations

import json
from pathlib import Path
import shutil

from tools.capture_facility_layout_p11_visuals import (
    VISUAL_SOURCE_PATHS as CAPTURE_SOURCE_PATHS,
    _visual_source_binding as capture_source_binding,
)
from tools.verify_facility_layout_p11 import (
    ROOT,
    VISUAL_CAPTURE_SOURCE,
    VISUAL_SOURCE_PATHS as VERIFIER_SOURCE_PATHS,
    _build_visual_source_binding,
    _visual_source_binding_status,
    build_visual_manifest,
)


def _write(root: Path, relative: str, value: str) -> None:
    path = root / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="ascii")


def test_capture_and_verifier_produce_the_same_deterministic_binding(
    tmp_path: Path,
):
    assert CAPTURE_SOURCE_PATHS == VERIFIER_SOURCE_PATHS
    paths = ("static/app.js", "static/app.css")
    _write(tmp_path, paths[0], "window.app = true;\n")
    _write(tmp_path, paths[1], ".app { display: block; }\n")

    captured = capture_source_binding(tmp_path, paths)
    verified = _build_visual_source_binding(tmp_path, paths)

    assert captured == verified
    assert captured["algorithm"] == "sha256"
    assert captured["aggregateAlgorithm"] == (
        "sha256-canonical-json-v1"
    )
    assert [item["path"] for item in captured["files"]] == sorted(paths)
    assert len(captured["aggregateSha256"]) == 64
    assert json.dumps(captured, sort_keys=True) == json.dumps(
        verified,
        sort_keys=True,
    )


def test_verifier_rejects_binding_after_source_changes(tmp_path: Path):
    paths = ("static/app.js", "static/app.css")
    _write(tmp_path, paths[0], "window.app = true;\n")
    _write(tmp_path, paths[1], ".app { display: block; }\n")
    captured = _build_visual_source_binding(tmp_path, paths)

    initial = _visual_source_binding_status(
        captured,
        root=tmp_path,
        relative_paths=paths,
    )
    assert initial["matches"] is True
    assert initial["stalePaths"] == []

    _write(tmp_path, paths[0], "window.app = false;\n")
    stale = _visual_source_binding_status(
        captured,
        root=tmp_path,
        relative_paths=paths,
    )

    assert stale["matches"] is False
    assert stale["filesMatch"] is False
    assert stale["aggregateMatches"] is False
    assert stale["stalePaths"] == ["static/app.js"]


def test_verifier_rejects_missing_unexpected_and_duplicate_inputs(
    tmp_path: Path,
):
    paths = ("static/app.js", "static/app.css")
    _write(tmp_path, paths[0], "window.app = true;\n")
    _write(tmp_path, paths[1], ".app { display: block; }\n")
    captured = _build_visual_source_binding(tmp_path, paths)
    captured["files"] = [
        captured["files"][0],
        captured["files"][0],
        {
            "path": "static/unexpected.js",
            "byteLength": 0,
            "sha256": "0" * 64,
        },
    ]

    status = _visual_source_binding_status(
        captured,
        root=tmp_path,
        relative_paths=paths,
    )

    assert status["matches"] is False
    assert status["requiredInputsExact"] is False
    assert status["missingPaths"] == ["static/app.js"]
    assert status["unexpectedPaths"] == ["static/unexpected.js"]
    assert status["duplicatePaths"] == ["static/app.css"]


def test_verifier_rejects_absent_source_binding(tmp_path: Path):
    paths = ("static/app.js",)
    _write(tmp_path, paths[0], "window.app = true;\n")

    status = _visual_source_binding_status(
        None,
        root=tmp_path,
        relative_paths=paths,
    )

    assert status["present"] is False
    assert status["matches"] is False
    assert status["missingPaths"] == ["static/app.js"]


def test_full_manifest_rejects_screenshots_after_bound_source_changes(
    tmp_path: Path,
):
    paths = ("static/app.js", "static/app.css")
    _write(tmp_path, paths[0], "window.app = true;\n")
    _write(tmp_path, paths[1], ".app { display: block; }\n")

    capture = json.loads(
        VISUAL_CAPTURE_SOURCE.read_text(encoding="ascii")
    )
    for record in capture["records"]:
        relative = record["path"]
        target = tmp_path / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    recovery_screenshot = capture.get(
        "webglContextRecovery",
        {},
    ).get("screenshot", {})
    recovery_relative = recovery_screenshot.get("path")
    if recovery_relative:
        recovery_target = tmp_path / recovery_relative
        recovery_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / recovery_relative, recovery_target)
    capture["schemaVersion"] = "facility-layout-p11-visual-capture-v2"
    capture["sourceBinding"] = _build_visual_source_binding(
        tmp_path,
        paths,
    )
    capture["sourceStableDuringCapture"] = True
    capture_path = tmp_path / "p11-visual-capture.json"
    capture_path.write_text(
        json.dumps(capture, indent=2, sort_keys=True) + "\n",
        encoding="ascii",
    )

    current = build_visual_manifest(
        capture_path,
        source_root=tmp_path,
        source_paths=paths,
        artifact_root=tmp_path,
    )
    assert current["manifestValid"] is True
    assert current["releaseGateMet"] is True
    assert all(
        item["sourceMatchesArtifact"] is True
        for item in current["artifacts"]
    )

    _write(tmp_path, paths[0], "window.app = false;\n")
    stale = build_visual_manifest(
        capture_path,
        source_root=tmp_path,
        source_paths=paths,
        artifact_root=tmp_path,
    )

    assert stale["manifestValid"] is False
    assert stale["releaseGateMet"] is False
    assert stale["sourceBinding"]["matches"] is False
    assert stale["sourceBinding"]["stalePaths"] == ["static/app.js"]
    assert all(
        item["sourceMatchesArtifact"] is True
        for item in stale["artifacts"]
    )
