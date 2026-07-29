from __future__ import annotations

import hashlib
import json
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).resolve().parents[1]
SPATIAL = ROOT / "tests" / "fixtures" / "facility_layout" / "spatial"
RESULT = SPATIAL / "p6-product-result.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _result() -> dict:
    return json.loads(RESULT.read_text(encoding="ascii"))


def test_p6_product_evidence_is_complete_and_green():
    result = _result()
    assert result["schemaVersion"] == "facility-layout-p6-product-evidence-v1"
    assert result["passed"] is True
    assert result["checks"]
    assert all(result["checks"].values())
    assert result["errors"] == {"console": [], "page": []}
    assert result["network"]["failedResponses"] == []


def test_p6_product_evidence_is_bound_to_current_sources():
    result = _result()
    paths = {
        "appSha256": ROOT / "static" / "facility_layout_app.js",
        "hostSha256": ROOT / "ai_inspector" / "facility_layout" / "host.py",
        "indexSha256": ROOT / "static" / "index.html",
        "serviceSha256": (
            ROOT / "ai_inspector" / "facility_layout" / "service.py"
        ),
        "sessionSha256": ROOT / "static" / "facility_layout_session.js",
        "spatialSha256": (
            ROOT / "ai_inspector" / "facility_layout" / "spatial.py"
        ),
        "threeAdapterSha256": (
            ROOT / "static" / "facility_layout_three_adapter.js"
        ),
        "transportSha256": ROOT / "static" / "facility_layout_transport.js",
        "verifierSha256": ROOT / "tools" / "verify_facility_layout_p6.py",
        "workspaceSha256": ROOT / "static" / "facility_layout_workspace.js",
    }
    assert set(result["source"]) == set(paths)
    for field, path in paths.items():
        assert result["source"][field] == _sha256(path)


def test_p6_product_screenshots_are_nonblank_and_current():
    for record in _result()["screenshots"].values():
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
