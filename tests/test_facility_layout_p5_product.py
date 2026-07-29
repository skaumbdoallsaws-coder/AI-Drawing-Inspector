from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
AUTHORING = ROOT / "tests" / "fixtures" / "facility_layout" / "authoring"
RESULT = AUTHORING / "p5-product-result.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result() -> dict:
    return json.loads(RESULT.read_text(encoding="ascii"))


def test_product_evidence_is_complete_and_green():
    result = _result()
    assert result["schemaVersion"] == "facility-layout-p5-product-evidence-v1"
    assert result["passed"] is True
    assert result["checks"]
    assert all(result["checks"].values())
    assert result["errors"] == {"console": [], "page": []}
    assert result["drop"]["createdWorld"] == result["drop"]["ghostWorld"]
    assert result["drop"]["after"] == result["drop"]["before"] + 1
    assert result["drop"]["afterUndo"] == result["drop"]["before"]


def test_product_evidence_is_bound_to_current_sources():
    result = _result()
    paths = {
        "appSha256": ROOT / "static" / "facility_layout_app.js",
        "editorSha256": ROOT / "static" / "facility_layout_editor.js",
        "hostSha256": ROOT / "ai_inspector" / "facility_layout" / "host.py",
        "indexSha256": ROOT / "static" / "index.html",
        "threeAdapterSha256": (
            ROOT / "static" / "facility_layout_three_adapter.js"
        ),
        "transportSha256": (
            ROOT / "static" / "facility_layout_transport.js"
        ),
        "threeClassicSha256": (
            ROOT
            / "static"
            / "vendor"
            / "three"
            / "0.128.0"
            / "build"
            / "three.min.js"
        ),
        "threeModuleSha256": (
            ROOT
            / "static"
            / "vendor"
            / "three"
            / "0.184.0"
            / "build"
            / "three.module.min.js"
        ),
        "orbitControlsSha256": (
            ROOT
            / "static"
            / "vendor"
            / "three"
            / "0.184.0"
            / "examples"
            / "jsm"
            / "controls"
            / "OrbitControls.js"
        ),
        "verifierSha256": (
            ROOT / "tools" / "verify_facility_layout_p5_product.py"
        ),
        "workspaceSha256": (
            ROOT / "static" / "facility_layout_workspace.js"
        ),
    }
    assert set(result["source"]) == set(paths)
    for field, path in paths.items():
        assert result["source"][field] == _sha256(path)


def test_product_screenshots_are_nonblank_and_current():
    result = _result()
    for record in result["screenshots"].values():
        path = ROOT / record["path"]
        assert path.is_file()
        assert record["sha256"] == _sha256(path)
        assert record["bytes"] == path.stat().st_size
        assert record["nonblank"] is True
        with Image.open(path) as image:
            assert [image.width, image.height] == [
                record["width"],
                record["height"],
            ]
