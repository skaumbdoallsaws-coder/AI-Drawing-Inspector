"""Tests for Library Intake Wizard Step 2 — preview + promote backend.

Validates the contract in docs/library-intake-wizard-plan.md sections
4 (user flow steps 10-11), 5 (canonical storage shape), 6 (safety
rules), 7 (validation), 9.2-9.4 (endpoints + lock), 10.1, 10.7.

Test ordering follows the user's stated scope: preview, promote,
no-overwrite, abort safety, real-profile protection.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterator, Tuple
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


# ── Fixture helpers ──────────────────────────────────────────────────


def _make_drawing_map(pn: str) -> dict:
    return {
        "schemaVersion": "1.0",
        "partNumber": pn,
        "sheets": [{"number": 1, "views": [{"id": "v1", "type": "front"}]}],
    }


def _make_part_json(pn: str, *, name: str = "", description: str = "") -> dict:
    return {
        "schemaVersion": "1.0",
        "partNumber": pn,
        "name": name or f"Test part {pn}",
        "description": description or "Fixture part for intake wizard tests",
        "features": [{"id": "f1", "type": "extrude"}, {"id": "f2", "type": "hole"}],
    }


def _make_sidecar_manifest(pn: str, package_id: str) -> dict:
    return {
        "schemaVersion": "1.0",
        "packageId": package_id,
        "partNumber": pn,
        "kind": "part",
        "featureCount": 46,
        "activeConfiguration": "Default",
        "sourceDocPath": f"C:\\dev\\{pn}.SLDPRT",
    }


def _seed_library(library: Path, pn: str = "1099999",
                  drawing_package_id: str = "deadbeef0001",
                  part_package_id: str = "deadbeef0002",
                  include_pdf: bool = True) -> Tuple[str, str]:
    """Populate a freshly-rooted library_dir with:
      - root {pn}_drawing_map.json   (post-/api/request-extraction state)
      - root {pn}_drawing.pdf        (optional)
      - sidecar at _bridge_imports/part/{pn}/{partPackageId}/
    Returns (drawing_package_id, part_package_id)."""
    (library / f"{pn}_drawing_map.json").write_text(json.dumps(_make_drawing_map(pn)), encoding="utf-8")
    if include_pdf:
        (library / f"{pn}_drawing.pdf").write_bytes(b"%PDF-1.4\nfake pdf for tests\n%%EOF")
    sidecar = library / "_bridge_imports" / "part" / pn / part_package_id
    (sidecar / "part").mkdir(parents=True)
    (sidecar / "part" / "part.json").write_text(json.dumps(_make_part_json(pn)), encoding="utf-8")
    (sidecar / "manifest.json").write_text(json.dumps(_make_sidecar_manifest(pn, part_package_id)), encoding="utf-8")
    return drawing_package_id, part_package_id


@pytest.fixture
def intake_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    library = tmp_path / "intake_lib"
    library.mkdir()
    _seed_library(library)
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    monkeypatch.setattr(server, "assembly_profiles", {}, raising=False)
    # Inspector instance is None until the FastAPI lifespan runs. The
    # promote handler tolerates inspector=None when calling
    # refresh_profile_index (guarded by `if inspector is not None`),
    # so tests don't need an inspector instance for the writes.
    monkeypatch.setattr(server, "inspector", None)
    yield library


def _default_body(pn: str = "1099999", revision: str = "revA",
                  drawing_package_id: str = "deadbeef0001",
                  part_package_id: str = "deadbeef0002",
                  overwrite_confirmed: str = None,
                  intake_mode: str = "brand-new-part") -> dict:
    body = {
        "partNumber": pn,
        "revision": revision,
        "intakeMode": intake_mode,
        "drawingPackageId": drawing_package_id,
        "partPackageId": part_package_id,
        "drawingSourceDocPath": f"C:\\dev\\{pn}.SLDDRW",
        "partSourceDocPath":    f"C:\\dev\\{pn}.SLDPRT",
        "drawingSheetCount": 1,
        "drawingViewCount":  1,
    }
    if overwrite_confirmed is not None:
        body["overwriteConfirmed"] = overwrite_confirmed
    return body


# ── Predicate / sanitizer ─────────────────────────────────────────────


def test_intake_sanitize_revision_accepts_canonical_revs():
    assert server._intake_sanitize_revision("revA") == "revA"
    assert server._intake_sanitize_revision("revB") == "revB"
    assert server._intake_sanitize_revision("revC1") == "revC1"
    assert server._intake_sanitize_revision(" revD ") == "revD"  # strip whitespace


def test_intake_sanitize_revision_rejects_anything_else():
    # Wrong prefix case
    assert server._intake_sanitize_revision("Rev_C") == ""
    assert server._intake_sanitize_revision("REVA") == ""
    # Non-alnum characters
    assert server._intake_sanitize_revision("rev-1") == ""
    assert server._intake_sanitize_revision("rev_1") == ""
    # Empty / non-string
    assert server._intake_sanitize_revision("") == ""
    assert server._intake_sanitize_revision(None) == ""
    # Distinct from the pre-existing stripper-style _sanitize_revision
    # which would have returned "RevC" here -- intake needs strict match
    # because the revision name lands in filesystem paths verbatim.


# ── Preview ───────────────────────────────────────────────────────────


def test_preview_brand_new_part_first_revision_returns_actions(intake_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview", json=_default_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["planValid"] is True
    assert body["partNumber"] == "1099999"
    assert body["revision"] == "revA"
    assert body["targetRevisionPath"].endswith("parts/1099999/revA")
    paths = [a["path"] for a in body["actions"]]
    # §5.1 per-rev files
    assert "parts/1099999/revA/1099999_drawing_map.json" in paths
    assert "parts/1099999/revA/1099999.json" in paths
    assert "parts/1099999/revA/1099999_drawing.pdf" in paths
    assert "parts/1099999/revA/intake_manifest.json" in paths
    assert "parts/1099999/revA/1099999_inspection_profile.json" in paths
    # Root files
    assert "1099999_drawing_map.json" in paths
    assert "1099999_drawing.pdf" in paths
    assert "1099999_inspection_profile.json" in paths
    # All per-rev actions for a brand-new part are CREATE (no overwrite)
    for a in body["actions"]:
        if a["path"].startswith("parts/1099999/revA/"):
            assert a["kind"] == "CREATE"


def test_preview_no_drawing_map_errors(intake_library: Path):
    (intake_library / "1099999_drawing_map.json").unlink()
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview", json=_default_body())
    body = r.json()
    assert body["planValid"] is False
    codes = [e["code"] for e in body["errors"]]
    assert "missing_drawing_map" in codes


def test_preview_no_part_sidecar_errors(intake_library: Path):
    import shutil
    shutil.rmtree(intake_library / "_bridge_imports")
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview", json=_default_body())
    body = r.json()
    assert body["planValid"] is False
    codes = [e["code"] for e in body["errors"]]
    assert "missing_part_sidecar" in codes


def test_preview_invalid_revision_string_errors(intake_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview", json=_default_body(revision="Rev_1"))
    body = r.json()
    assert body["planValid"] is False
    codes = [e["code"] for e in body["errors"]]
    assert "invalid_revision" in codes


def test_preview_invalid_intake_mode_errors(intake_library: Path):
    body_in = _default_body()
    body_in["intakeMode"] = "totally-made-up-mode"
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview", json=body_in)
    body = r.json()
    assert body["planValid"] is False
    codes = [e["code"] for e in body["errors"]]
    assert "invalid_intake_mode" in codes


def test_preview_revision_exists_without_overwrite_blocks(intake_library: Path):
    # Pre-create the target revision dir
    (intake_library / "parts" / "1099999" / "revA").mkdir(parents=True)
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview", json=_default_body())
    body = r.json()
    assert body["planValid"] is False
    codes = [e["code"] for e in body["errors"]]
    assert "revision_exists" in codes


def test_preview_revision_exists_with_overwrite_confirmed_proceeds(intake_library: Path):
    (intake_library / "parts" / "1099999" / "revA").mkdir(parents=True)
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview",
                    json=_default_body(overwrite_confirmed="revA"))
    body = r.json()
    assert body["planValid"] is True
    # Per-rev actions now kind=OVERWRITE
    per_rev = [a for a in body["actions"] if a["path"].startswith("parts/1099999/revA/")]
    assert per_rev
    assert all(a["kind"] == "OVERWRITE" for a in per_rev)


def test_preview_overwrite_confirmed_wrong_string_blocks(intake_library: Path):
    (intake_library / "parts" / "1099999" / "revA").mkdir(parents=True)
    client = TestClient(server.app)
    # User typed revB but the existing revision is revA -- must not bypass
    r = client.post("/api/library/intake/preview",
                    json=_default_body(overwrite_confirmed="revB"))
    body = r.json()
    assert body["planValid"] is False
    assert any(e["code"] == "revision_exists" for e in body["errors"])


def test_preview_real_profile_at_root_skips_stub_actions(intake_library: Path):
    # Place a real (non-stub) inspection profile at root
    (intake_library / "1099999_inspection_profile.json").write_text(json.dumps({
        "part_number": "1099999",
        "part_name":   "Hand-authored real profile",
        "features":    [{"name": "Critical bore", "type": "hole", "count": 1}],
    }), encoding="utf-8")
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview", json=_default_body())
    body = r.json()
    assert body["planValid"] is True
    # Warning surfaces the protection
    codes = [w["code"] for w in body["warnings"]]
    assert "real_profile_protected" in codes
    # Per-rev stub action SHOULD NOT appear
    paths = [a["path"] for a in body["actions"]]
    assert "parts/1099999/revA/1099999_inspection_profile.json" not in paths
    # Root stub: SKIP action present
    skip_actions = [a for a in body["actions"] if a["kind"] == "SKIP"]
    assert any(a["path"] == "1099999_inspection_profile.json" for a in skip_actions)


# ── Promote ───────────────────────────────────────────────────────────


def test_promote_writes_per_revision_layout(intake_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    rev_dir = intake_library / "parts" / "1099999" / "revA"
    assert (rev_dir / "1099999_drawing_map.json").exists()
    assert (rev_dir / "1099999.json").exists()
    assert (rev_dir / "1099999_drawing.pdf").exists()
    assert (rev_dir / "intake_manifest.json").exists()
    assert (rev_dir / "1099999_inspection_profile.json").exists()
    # No leftover .partial dir
    assert not (intake_library / "parts" / "1099999" / "revA.partial").exists()


def test_promote_writes_intake_manifest_contents(intake_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    assert r.status_code == 200, r.text
    manifest_path = intake_library / "parts" / "1099999" / "revA" / "intake_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    # §5.4 required fields
    assert manifest["schemaVersion"] == "1.0.0"
    assert manifest["partNumber"] == "1099999"
    assert manifest["revision"] == "revA"
    assert manifest["intakeMode"] == "brand-new-part"
    assert manifest["sourceDrawing"]["packageId"] == "deadbeef0001"
    assert manifest["sourceDrawing"]["sourceDocPath"] == "C:\\dev\\1099999.SLDDRW"
    assert manifest["sourceDrawing"]["sheetCount"] == 1
    assert manifest["sourcePart"]["packageId"] == "deadbeef0002"
    # Enriched from sidecar manifest.json
    assert manifest["sourcePart"]["featureCount"] == 46
    assert manifest["sourcePart"]["activeConfiguration"] == "Default"
    # bridgeBaseline pins both sides per §5.4
    assert manifest["bridgeBaseline"]["addinCommit"]
    assert manifest["bridgeBaseline"]["appCommit"]
    # Files list lines up with what was written
    file_paths = {f["path"] for f in manifest["files"]}
    assert "1099999_drawing_map.json" in file_paths
    assert "1099999.json" in file_paths
    assert "1099999_drawing.pdf" in file_paths


def test_promote_carries_all_metadata_fields_into_manifest(intake_library: Path):
    """Regression for the 'intake_manifest had blank/null drawing
    metadata' smoke bug. Drawing extraction has no on-disk sidecar
    for the backend to enrich from (the staging zip is cleaned up
    by /api/request-extraction's atomic install), so the body fields
    are the ONLY source for sourceDrawing.packageId / sheetCount /
    viewCount / sourceDocPath in intake_manifest.json. Confirm every
    field the wizard now passes survives the round-trip into the
    manifest, AND that body fields take precedence over sidecar
    enrichment for part metadata."""
    # Remove the sidecar manifest so backend enrichment cannot mask a
    # missing pass-through (this test isolates body -> manifest).
    sidecar_manifest = (intake_library / "_bridge_imports" / "part"
                        / "1099999" / "deadbeef0002" / "manifest.json")
    if sidecar_manifest.exists():
        sidecar_manifest.unlink()

    body = _default_body()
    body["drawingPackageId"]        = "DRAWING_PKG_001"
    body["drawingSheetCount"]       = 3
    body["drawingViewCount"]        = 12
    body["drawingSourceDocPath"]    = "C:/cad/big-drawing.SLDDRW"
    body["partFeatureCount"]        = 99
    body["partActiveConfiguration"] = "TestConfig"
    body["partSourceDocPath"]       = "C:/cad/small-part.SLDPRT"

    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=body)
    assert r.status_code == 200, r.text

    manifest = json.loads((intake_library / "parts" / "1099999" / "revA" / "intake_manifest.json").read_text(encoding="utf-8"))
    # Drawing block: every body field must survive into the manifest.
    assert manifest["sourceDrawing"]["packageId"]     == "DRAWING_PKG_001"
    assert manifest["sourceDrawing"]["sheetCount"]    == 3
    assert manifest["sourceDrawing"]["viewCount"]     == 12
    assert manifest["sourceDrawing"]["sourceDocPath"] == "C:/cad/big-drawing.SLDDRW"
    # Part block: body wins over absent sidecar enrichment.
    assert manifest["sourcePart"]["packageId"]           == "deadbeef0002"
    assert manifest["sourcePart"]["featureCount"]        == 99
    assert manifest["sourcePart"]["activeConfiguration"] == "TestConfig"
    assert manifest["sourcePart"]["sourceDocPath"]       == "C:/cad/small-part.SLDPRT"


def test_promote_writes_stub_at_root_and_per_rev(intake_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    assert r.status_code == 200
    # Root stub
    root_stub_path = intake_library / "1099999_inspection_profile.json"
    assert root_stub_path.exists()
    root_stub = json.loads(root_stub_path.read_text(encoding="utf-8"))
    assert root_stub["source"] == "library_intake_stub"
    assert root_stub["inspectionReady"] is False
    assert root_stub["status"] == "incomplete"
    # Per-rev stub archive
    per_rev_stub_path = intake_library / "parts" / "1099999" / "revA" / "1099999_inspection_profile.json"
    assert per_rev_stub_path.exists()
    per_rev_stub = json.loads(per_rev_stub_path.read_text(encoding="utf-8"))
    assert per_rev_stub["source"] == "library_intake_stub"


def test_promote_skips_stub_when_real_profile_at_root(intake_library: Path):
    # Real profile present
    real_profile_bytes = json.dumps({
        "part_number": "1099999",
        "part_name":   "Hand-authored",
        "features":    [{"name": "Bore", "type": "hole", "count": 1}],
    }, indent=2).encode("utf-8")
    real_profile_path = intake_library / "1099999_inspection_profile.json"
    real_profile_path.write_bytes(real_profile_bytes)
    mtime_before = real_profile_path.stat().st_mtime_ns

    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    assert r.status_code == 200
    body = r.json()
    assert body["success"] is True
    # Root real profile content + mtime unchanged
    assert real_profile_path.read_bytes() == real_profile_bytes
    assert real_profile_path.stat().st_mtime_ns == mtime_before
    # No per-rev stub written
    per_rev_stub_path = intake_library / "parts" / "1099999" / "revA" / "1099999_inspection_profile.json"
    assert not per_rev_stub_path.exists()


def test_promote_creates_root_drawing_map_backup_on_update(intake_library: Path):
    # Promote once -- now the root drawing map exists (was seeded too).
    client = TestClient(server.app)
    client.post("/api/library/intake/promote", json=_default_body())
    # Modify root drawing map to a known-different content, then promote a
    # second revision. The second promote should .bak the modified content
    # before installing the new map.
    custom_marker = json.dumps({"partNumber": "1099999", "marker": "manually-edited"})
    root_map = intake_library / "1099999_drawing_map.json"
    root_map.write_text(custom_marker, encoding="utf-8")

    r = client.post("/api/library/intake/promote", json=_default_body(revision="revB"))
    assert r.status_code == 200, r.text
    bak = root_map.with_suffix(root_map.suffix + ".bak")
    assert bak.exists(), "expected .bak rollback of root drawing map on second promote"
    assert bak.read_text(encoding="utf-8") == custom_marker


def test_promote_blocked_without_overwrite_when_revision_exists(intake_library: Path):
    (intake_library / "parts" / "1099999" / "revA").mkdir(parents=True)
    # Drop a sentinel file that should NOT disappear on a blocked promote
    sentinel = intake_library / "parts" / "1099999" / "revA" / "manual.notes.txt"
    sentinel.write_text("hand-edited inspection notes -- do not lose", encoding="utf-8")

    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    assert r.status_code == 409
    body = r.json()
    assert body["planValid"] is False
    assert any(e["code"] == "revision_exists" for e in body["errors"])
    # Sentinel must still exist -- blocked promote does NOT touch the dir
    assert sentinel.read_text(encoding="utf-8").startswith("hand-edited")


def test_promote_overwrite_preserves_unmanaged_files_in_existing_revision(intake_library: Path):
    """§6.4: 'Files under parts/{pn}/rev{X}/ that the wizard does NOT
    manage are never touched.' Confirmed-overwrite path must leave
    curated .STL / .glb / view PNGs alone."""
    rev_dir = intake_library / "parts" / "1099999" / "revA"
    rev_dir.mkdir(parents=True)
    curated = rev_dir / "1099999.STL"
    curated.write_bytes(b"FAKE STL CONTENT")
    curated_mtime = curated.stat().st_mtime_ns

    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote",
                    json=_default_body(overwrite_confirmed="revA"))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["success"] is True
    # Curated file untouched
    assert curated.read_bytes() == b"FAKE STL CONTENT"
    assert curated.stat().st_mtime_ns == curated_mtime
    # Wizard-managed files were overwritten / created
    assert (rev_dir / "1099999_drawing_map.json").exists()
    assert (rev_dir / "intake_manifest.json").exists()


def test_promote_aborts_safely_on_per_rev_rename_failure(intake_library: Path,
                                                         monkeypatch: pytest.MonkeyPatch):
    """§6.2 abort safety: if the atomic flip from `.partial` to the
    target revision dir fails (the riskiest moment — partial is fully
    built, ready to commit), the .partial dir is rmtree'd and no
    library state is visible. Simulate by patching os.rename to raise
    when it sees the .partial path."""
    real_rename = os.rename

    def failing_rename(src, dst, *args, **kwargs):
        if str(src).endswith(".partial"):
            raise OSError("simulated atomic-flip failure")
        return real_rename(src, dst, *args, **kwargs)

    monkeypatch.setattr(server.os, "rename", failing_rename)

    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    # 500 because per-rev write failed
    assert r.status_code == 500
    body = r.json()
    assert body["success"] is False
    # Target rev dir was never created (rename failed before flip)
    assert not (intake_library / "parts" / "1099999" / "revA").exists()
    # .partial dir was rmtree'd by the rollback path -- no visible state
    assert not (intake_library / "parts" / "1099999" / "revA.partial").exists()
    # Root files (drawing_map, etc.) were NOT updated either since per-rev
    # came first and the function returned before the root install phase.
    # The seeded root drawing_map is still the original fixture content.
    seeded = json.loads((intake_library / "1099999_drawing_map.json").read_text(encoding="utf-8"))
    assert seeded == _make_drawing_map("1099999")


def test_promote_does_not_delete_bridge_imports_sidecar(intake_library: Path):
    """§6.6: the wizard never touches _bridge_imports/. After a
    successful promote, the sidecar is still on disk."""
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    assert r.status_code == 200
    sidecar_partjson = (intake_library / "_bridge_imports" / "part" / "1099999"
                        / "deadbeef0002" / "part" / "part.json")
    assert sidecar_partjson.exists(), "wizard must NOT delete bridge sidecar"


# ── Model-only intake mode ────────────────────────────────────────────


def test_preview_model_only_does_not_require_drawing(intake_library: Path):
    """modelOnly=True must skip the missing_drawing_map gate so a
    brand-new SLDPRT-only intake can preview cleanly."""
    # Remove the seeded drawing map so we are genuinely drawing-less
    (intake_library / "1099999_drawing_map.json").unlink()
    body = _default_body()
    body["modelOnly"] = True
    client = TestClient(server.app)
    r = client.post("/api/library/intake/preview", json=body)
    assert r.status_code == 200, r.text
    plan = r.json()
    assert plan["planValid"] is True
    assert plan["modelOnly"] is True
    # No drawing-map action in the plan
    paths = [a["path"] for a in plan["actions"]]
    assert not any("drawing_map" in p or "drawing.pdf" in p for p in paths), \
        f"unexpected drawing rows in model-only plan: {paths}"
    # Part + manifest + stub still planned
    assert any(p.endswith("/1099999.json")              for p in paths)
    assert any(p.endswith("/intake_manifest.json")      for p in paths)
    # Stub still planned (no real profile at root in this fixture)
    assert any(p.endswith("/1099999_inspection_profile.json") for p in paths)


def test_promote_model_only_writes_no_drawing_files(intake_library: Path):
    """Model-only promote must not write the drawing map or PDF -- at
    per-rev OR at root. Confirms both halves of fix #2 in the
    stabilization pass still apply (drawing path is gated, not silently
    re-installed)."""
    # Remove seeded drawing fixtures so a leak would be visible
    (intake_library / "1099999_drawing_map.json").unlink()
    if (intake_library / "1099999_drawing.pdf").exists():
        (intake_library / "1099999_drawing.pdf").unlink()
    body = _default_body()
    body["modelOnly"] = True
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=body)
    assert r.status_code == 200, r.text
    rev_dir = intake_library / "parts" / "1099999" / "revA"
    assert not (rev_dir / "1099999_drawing_map.json").exists()
    assert not (rev_dir / "1099999_drawing.pdf").exists()
    assert not (intake_library / "1099999_drawing_map.json").exists()
    assert not (intake_library / "1099999_drawing.pdf").exists()
    # But part + manifest + stub ARE written
    assert (rev_dir / "1099999.json").exists()
    assert (rev_dir / "intake_manifest.json").exists()
    assert (rev_dir / "1099999_inspection_profile.json").exists()
    assert (intake_library / "1099999_inspection_profile.json").exists()
    # The stub is the gate: inspectionReady must be False so the Step 1
    # surface keeps the Inspect button disabled.
    root_stub = json.loads((intake_library / "1099999_inspection_profile.json").read_text(encoding="utf-8"))
    assert root_stub["source"] == "library_intake_stub"
    assert root_stub["inspectionReady"] is False


def test_promote_model_only_manifest_omits_drawing_map_files_entry(intake_library: Path):
    """intake_manifest.files[] must NOT list a drawing_map row when the
    promote is model-only (the file wasn't written)."""
    (intake_library / "1099999_drawing_map.json").unlink()
    body = _default_body()
    body["modelOnly"] = True
    client = TestClient(server.app)
    client.post("/api/library/intake/promote", json=body)
    manifest = json.loads((intake_library / "parts" / "1099999" / "revA" / "intake_manifest.json").read_text(encoding="utf-8"))
    file_paths = {f["path"] for f in manifest["files"]}
    assert "1099999_drawing_map.json" not in file_paths
    assert "1099999.json"             in file_paths


def test_promote_model_only_revB_after_real_revA_does_not_touch_root_drawing_map(intake_library: Path):
    """If revA was promoted with a drawing (standard mode) and the
    operator later promotes revB as model-only, the root pointer must
    remain at revA's drawing map. The acceptance test's revA-then-revB
    scenario depends on this -- otherwise revB would silently invalidate
    the root pointer."""
    # First, standard revA promote (drawing present from fixture)
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body(revision="revA"))
    assert r.status_code == 200, r.text
    root_map_after_revA = (intake_library / "1099999_drawing_map.json").read_bytes()
    # Capture the root mtime before revB so a silent overwrite would
    # advance it even if the bytes happen to match.
    import time as _t
    root_map_path = intake_library / "1099999_drawing_map.json"
    mtime_before = root_map_path.stat().st_mtime_ns
    _t.sleep(0.05)  # ensure any subsequent write would have a later mtime
    # Now model-only revB
    body = _default_body(revision="revB")
    body["modelOnly"] = True
    r = client.post("/api/library/intake/promote", json=body)
    assert r.status_code == 200, r.text
    # Root pointer unchanged -- byte-equal AND mtime unchanged. The mtime
    # check is the load-bearing one: a buggy model-only path that
    # re-installed the same drawing-map bytes would still bump mtime.
    assert root_map_path.read_bytes() == root_map_after_revA
    assert root_map_path.stat().st_mtime_ns == mtime_before, \
        "model-only revB silently re-installed the root drawing map (mtime advanced)"


# ── Visual asset promotion (task 3 of extractor-parity pass) ──────────


def _seed_visual_assets(sidecar_pkg_root: Path, pn: str = "1099999"):
    """Drop simulated GLB + feature_colors + 4 view PNGs + STL inside
    the sidecar package's part/ subdirectory. Today's shipped bridge
    does not emit these, but the wizard treats them as copy-if-present
    so a future bridge enhancement (or a manual operator drop) flows
    straight through."""
    part_subdir = sidecar_pkg_root / "part"
    part_subdir.mkdir(parents=True, exist_ok=True)
    (part_subdir / f"{pn}_colored.glb").write_bytes(b"glTF\x02\x00\x00\x00")
    (part_subdir / f"{pn}_feature_colors.json").write_text('{"f1":"#ff0000"}', encoding="utf-8")
    (part_subdir / f"{pn}_view_front.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (part_subdir / f"{pn}_view_top.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (part_subdir / f"{pn}_view_right.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (part_subdir / f"{pn}_view_isometric.png").write_bytes(b"\x89PNG\r\n\x1a\n")
    (part_subdir / f"{pn}.stl").write_text("solid", encoding="utf-8")


def test_promote_copies_visual_assets_from_sidecar_when_present(intake_library: Path):
    """When the sidecar has GLB / view PNGs / STL / feature_colors, the
    promote copies them into the per-rev archive. Defensive forward-
    compat for the bridge's planned visual export."""
    pkg_root = intake_library / "_bridge_imports" / "part" / "1099999" / "deadbeef0002"
    _seed_visual_assets(pkg_root)
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    assert r.status_code == 200, r.text
    rev_dir = intake_library / "parts" / "1099999" / "revA"
    assert (rev_dir / "1099999_colored.glb").exists()
    assert (rev_dir / "1099999_feature_colors.json").exists()
    assert (rev_dir / "1099999_view_front.png").exists()
    assert (rev_dir / "1099999_view_top.png").exists()
    assert (rev_dir / "1099999_view_right.png").exists()
    assert (rev_dir / "1099999_view_isometric.png").exists()
    assert (rev_dir / "1099999.stl").exists()


def test_promote_preserves_curated_visual_assets_on_overwrite(intake_library: Path):
    """When the operator already placed a curated GLB in the per-rev
    folder, OVERWRITE mode must NOT clobber it with the sidecar copy.
    Mirrors §6.4 (preserve unmanaged files); the visual asset is treated
    as 'unmanaged once present' because the operator's hand-placed copy
    may be higher-quality than whatever the bridge produced."""
    # Pre-create the rev dir with a curated GLB
    rev_dir = intake_library / "parts" / "1099999" / "revA"
    rev_dir.mkdir(parents=True)
    curated = rev_dir / "1099999_colored.glb"
    curated_bytes = b"CURATED_GLB_DO_NOT_OVERWRITE"
    curated.write_bytes(curated_bytes)
    # Sidecar has a different GLB
    pkg_root = intake_library / "_bridge_imports" / "part" / "1099999" / "deadbeef0002"
    _seed_visual_assets(pkg_root)
    # Confirmed-overwrite promote
    body = _default_body(overwrite_confirmed="revA")
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=body)
    assert r.status_code == 200, r.text
    # Curated GLB survives byte-for-byte; sidecar's STL (no prior
    # curated copy) lands fresh.
    assert curated.read_bytes() == curated_bytes
    assert (rev_dir / "1099999.stl").exists()


def test_promote_no_visual_assets_in_sidecar_is_no_op(intake_library: Path):
    """The today-bridge case: sidecar has only manifest.json + part.json,
    no visual assets. Promote completes cleanly; the action list does
    not gain any visual-asset rows (CREATE or SKIP)."""
    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=_default_body())
    assert r.status_code == 200, r.text
    rev_dir = intake_library / "parts" / "1099999" / "revA"
    # No visual asset files in per-rev (because none in sidecar)
    assert not (rev_dir / "1099999_colored.glb").exists()
    assert not (rev_dir / "1099999.stl").exists()
    # Action list should not have any visual-asset entries
    body = r.json()
    for a in body["executed"]:
        assert "colored.glb"      not in a["path"]
        assert "view_front.png"   not in a["path"]
        assert ".stl"             not in a["path"]


def test_visual_assets_helper_scans_both_pkg_root_and_part_subdir(intake_library: Path):
    """The helper checks the package's part/ subdirectory first, then
    falls back to the package root. Either location should yield the
    file. Documents the defensive scan because the bridge's eventual
    layout for visual assets is not yet pinned."""
    pkg_root = intake_library / "_bridge_imports" / "part" / "1099999" / "deadbeef0002"
    # Drop a GLB at the pkg root (NOT in part/)
    (pkg_root / "1099999_colored.glb").write_bytes(b"glTF")
    found = server._intake_visual_assets_in_sidecar(intake_library, "1099999", "deadbeef0002")
    found_names = [p.name for p in found]
    assert "1099999_colored.glb" in found_names


# ── Single-flight lock smoke ──────────────────────────────────────────


def test_promote_single_flight_lock_returns_409_when_busy(intake_library: Path,
                                                          monkeypatch: pytest.MonkeyPatch):
    """§9.4: concurrent promotes are rejected with 409 'one at a time'.
    Simulate by holding the lock manually before issuing the request."""
    # Acquire the lock from outside the event loop using a small async
    # helper so the TestClient request sees a busy lock.
    import asyncio

    async def _acquire():
        await server._library_intake_lock.acquire()

    loop = asyncio.new_event_loop()
    loop.run_until_complete(_acquire())
    try:
        client = TestClient(server.app)
        r = client.post("/api/library/intake/promote", json=_default_body())
        assert r.status_code == 409
        assert "in progress" in r.json()["detail"]
    finally:
        server._library_intake_lock.release()
        loop.close()


# ── Wizard overwrite bug (1030034 RevA/RevB cross-wire) ───────────────


def _make_real_bridge_manifest(pn: str, package_id: str,
                                source_doc_path: str,
                                configuration: str = "Default") -> dict:
    """The REAL shipped bridge writes a top-level `sourceDocument` dict
    (path / filePath / configurationName / fileSize / swModifiedAt /
    documentType). This helper models that shape so the rehydration
    tests catch regressions against the actual on-disk layout, not the
    legacy/synthetic shape used by _make_sidecar_manifest."""
    return {
        "schemaVersion":  "1.0",
        "packageId":      package_id,
        "partNumber":     pn,
        "kind":           "part",
        "sourceDocument": {
            "path":              source_doc_path,
            "filePath":          source_doc_path,
            "configurationName": configuration,
            "fileSize":          12345,
            "documentType":      "Part",
        },
    }


def _make_real_bridge_part_json(pn: str, configuration: str = "Default",
                                feature_count: int = 7) -> dict:
    """REAL bridge part.json: top-level activeConfiguration and a
    featureTree list. `featureCount` is computed as len(featureTree)."""
    return {
        "schemaVersion":       "1.0",
        "units":               "inch",
        "documentType":        "Part",
        "activeConfiguration": configuration,
        "featureTree":         [{"id": f"f{i}", "type": "feature"} for i in range(feature_count)],
    }


def _seed_real_shape_sidecar(library: Path, pn: str, package_id: str,
                              source_doc_path: str,
                              configuration: str = "Default",
                              feature_count: int = 7) -> None:
    sidecar = library / "_bridge_imports" / "part" / pn / package_id
    (sidecar / "part").mkdir(parents=True)
    (sidecar / "part" / "part.json").write_text(
        json.dumps(_make_real_bridge_part_json(pn, configuration, feature_count)),
        encoding="utf-8")
    (sidecar / "manifest.json").write_text(
        json.dumps(_make_real_bridge_manifest(pn, package_id, source_doc_path, configuration)),
        encoding="utf-8")


def test_library_revisions_endpoint_exposes_existing_rev_package_id(intake_library: Path):
    """The wizard frontend defaults Step 2 partPackageId from each
    revision's own intake_manifest.sourcePart.packageId (not _latest).
    The /api/library/revisions endpoint must surface that nested field
    so the frontend can read it without a second round-trip."""
    # Promote revA and revB with two different package IDs
    pn = "1099999"
    revA_pkg = "deadbeef0002"   # the default from the fixture
    revB_pkg = "feedface0099"
    # Seed a 2nd sidecar (real-shape) for revB
    _seed_real_shape_sidecar(intake_library, pn, revB_pkg,
                             source_doc_path=f"C:\\dev\\{pn}-RevB.SLDPRT",
                             configuration="Default", feature_count=11)

    client = TestClient(server.app)
    r1 = client.post("/api/library/intake/promote",
                     json=_default_body(revision="revA", part_package_id=revA_pkg))
    assert r1.status_code == 200, r1.text
    r2 = client.post("/api/library/intake/promote",
                     json=_default_body(revision="revB", part_package_id=revB_pkg))
    assert r2.status_code == 200, r2.text

    rv = client.get(f"/api/library/revisions/{pn}")
    assert rv.status_code == 200, rv.text
    data = rv.json()
    by_name = {r["name"]: r for r in data["revisions"]}
    # Each rev exposes intakeManifest.sourcePart.packageId distinctly
    assert by_name["revA"]["intakeManifest"]["sourcePart"]["packageId"] == revA_pkg
    assert by_name["revB"]["intakeManifest"]["sourcePart"]["packageId"] == revB_pkg
    # Critical: even though _latest.txt points wherever the LAST bridge
    # extraction landed, each revision's manifest holds its own truth.
    # The frontend uses intakeManifest.sourcePart.packageId as the
    # default for an existing revision rather than lastBridgePartPackageId.
    assert by_name["revA"]["intakeManifest"]["sourcePart"]["packageId"] \
        != by_name["revB"]["intakeManifest"]["sourcePart"]["packageId"]


def test_promote_blocks_package_id_change_for_existing_rev_without_ack(intake_library: Path):
    """The 1030034 cross-wire bug: re-promoting revA must not silently
    swap in a different package (e.g. the one _latest.txt points at).
    Without packageIdChangeAcknowledged=true, the promote returns 409
    with error code 'package_id_changed_for_existing_revision' and
    leaves the existing revision untouched."""
    pn = "1099999"
    revA_pkg = "deadbeef0002"
    wrong_pkg = "00ff00ff00ff"
    # First promote revA with the correct package
    client = TestClient(server.app)
    r1 = client.post("/api/library/intake/promote",
                     json=_default_body(revision="revA", part_package_id=revA_pkg))
    assert r1.status_code == 200, r1.text
    rev_dir = intake_library / "parts" / pn / "revA"
    manifest_before = (rev_dir / "intake_manifest.json").read_bytes()

    # Seed a real-shape sidecar for the WRONG package (mimics
    # _latest.txt pointing at a fresh bridge extraction of a sibling
    # rev) so the body's partPackageId resolves to an existing sidecar.
    _seed_real_shape_sidecar(intake_library, pn, wrong_pkg,
                             source_doc_path=f"C:\\dev\\{pn}-WRONG.SLDPRT")

    # Re-promote revA with the WRONG package + overwriteConfirmed but
    # WITHOUT packageIdChangeAcknowledged. Must 409.
    body = _default_body(revision="revA", part_package_id=wrong_pkg,
                         overwrite_confirmed="revA")
    r2 = client.post("/api/library/intake/promote", json=body)
    assert r2.status_code == 409, r2.text
    payload = r2.json()
    codes = [e["code"] for e in payload.get("errors", [])]
    assert "package_id_changed_for_existing_revision" in codes, codes
    # Detail message names both package IDs so the operator sees what's
    # being swapped (frontend renders this in the wizard error list).
    msg = next(e["message"] for e in payload["errors"]
               if e["code"] == "package_id_changed_for_existing_revision")
    assert revA_pkg in msg
    assert wrong_pkg in msg
    # Existing manifest untouched -- blocked promote must not write
    assert (rev_dir / "intake_manifest.json").read_bytes() == manifest_before


def test_promote_rehydrates_missing_part_metadata_from_real_bridge_sidecar(intake_library: Path):
    """When the wizard body omits partFeatureCount /
    partActiveConfiguration / partSourceDocPath (e.g. the operator
    opens the wizard fresh after a server restart and the
    window._lastBridgeExtractions cache is empty), the promote
    backend must rehydrate from the REAL bridge sidecar shape:
      - part.json -> top-level activeConfiguration, len(featureTree)
      - manifest.json -> sourceDocument.path / configurationName"""
    pn = "1099999"
    real_pkg = "abc123def456"
    # Replace the synthetic sidecar with the real bridge shape
    (intake_library / "_bridge_imports" / "part" / pn / "deadbeef0002").mkdir(parents=True, exist_ok=True)
    _seed_real_shape_sidecar(intake_library, pn, real_pkg,
                             source_doc_path=r"C:\cad\real-bridge\Mounting Plate.SLDPRT",
                             configuration="HighDetail", feature_count=42)

    # Send a body with ONLY the package IDs -- no part metadata at all.
    body = _default_body(part_package_id=real_pkg)
    # Strip the part-metadata fields _default_body normally provides
    body.pop("partSourceDocPath", None)
    body.pop("partFeatureCount", None)
    body.pop("partActiveConfiguration", None)

    client = TestClient(server.app)
    r = client.post("/api/library/intake/promote", json=body)
    assert r.status_code == 200, r.text

    manifest = json.loads(
        (intake_library / "parts" / pn / "revA" / "intake_manifest.json").read_text(encoding="utf-8")
    )
    sp = manifest["sourcePart"]
    # All three fields backfilled from the real bridge sidecar
    assert sp["packageId"]           == real_pkg
    assert sp["featureCount"]        == 42, sp
    assert sp["activeConfiguration"] == "HighDetail", sp
    assert sp["sourceDocPath"]       == r"C:\cad\real-bridge\Mounting Plate.SLDPRT", sp


def test_promote_with_acknowledged_package_change_deletes_stale_managed_visuals(intake_library: Path):
    """When operator acknowledges a package swap for an existing
    revision, the wizard's managed visual whitelist files (the old
    package's GLB / view PNGs / feature_colors / STL) must be deleted
    so the new package's visuals can take their place. Curated,
    non-managed files in the per-rev dir stay put."""
    pn = "1099999"
    revA_pkg = "deadbeef0002"
    new_pkg  = "facefacefac3"

    # Promote revA with the original package + seed visual assets in
    # the per-rev archive so we have something stale to remove later.
    _seed_visual_assets(intake_library / "_bridge_imports" / "part" / pn / revA_pkg, pn)
    client = TestClient(server.app)
    r1 = client.post("/api/library/intake/promote",
                     json=_default_body(revision="revA", part_package_id=revA_pkg))
    assert r1.status_code == 200, r1.text
    rev_dir = intake_library / "parts" / pn / "revA"
    stale_glb = rev_dir / f"{pn}_colored.glb"
    stale_iso = rev_dir / f"{pn}_view_isometric.png"
    assert stale_glb.exists()
    assert stale_iso.exists()
    stale_glb_bytes = stale_glb.read_bytes()

    # Drop a curated, NON-managed file the wizard must preserve
    curated = rev_dir / "operator_notes.txt"
    curated.write_text("hand-edited inspection notes -- do not lose", encoding="utf-8")

    # Seed the NEW package sidecar with different visual bytes
    new_pkg_root = intake_library / "_bridge_imports" / "part" / pn / new_pkg
    _seed_real_shape_sidecar(intake_library, pn, new_pkg,
                             source_doc_path=f"C:\\dev\\{pn}-RevA-repack.SLDPRT")
    # Distinct visual asset content so we can prove the swap
    (new_pkg_root / "part" / f"{pn}_colored.glb").write_bytes(b"NEW_PKG_GLB_BYTES")
    (new_pkg_root / "part" / f"{pn}_view_isometric.png").write_bytes(b"\x89PNG\r\n\x1a\nNEW")

    # Re-promote revA with the NEW package + overwriteConfirmed + ack
    body = _default_body(revision="revA", part_package_id=new_pkg,
                         overwrite_confirmed="revA")
    body["packageIdChangeAcknowledged"] = True
    r2 = client.post("/api/library/intake/promote", json=body)
    assert r2.status_code == 200, r2.text

    # Managed visuals replaced (not preserved)
    assert stale_glb.exists()  # file present again but with NEW bytes
    assert stale_glb.read_bytes() == b"NEW_PKG_GLB_BYTES", \
        "stale GLB from old package should have been deleted, then replaced from new pkg"
    assert stale_iso.read_bytes() == b"\x89PNG\r\n\x1a\nNEW", \
        "stale isometric PNG from old package should have been replaced"
    # Non-managed curated file untouched
    assert curated.read_text(encoding="utf-8").startswith("hand-edited")
    # Manifest reflects the new package
    manifest = json.loads((rev_dir / "intake_manifest.json").read_text(encoding="utf-8"))
    assert manifest["sourcePart"]["packageId"] == new_pkg


def test_promote_replaces_managed_visuals_on_same_package_when_flag_set(intake_library: Path):
    """Operator clicks Enrich Visuals in Step 3, sidecar gets refreshed
    GLB / view PNGs / STL, then Promote runs again WITHOUT a package id
    change. Wizard sends replaceManagedVisuals=true so the per-rev's
    wizard-managed visual whitelist is overwritten with the fresh
    sidecar bytes -- otherwise copy-if-not-exists would silently skip
    them and the operator's just-enriched assets would never land."""
    pn = "1099999"
    pkg = "deadbeef0002"
    # First promote with visual assets so the per-rev has stale bytes.
    pkg_root = intake_library / "_bridge_imports" / "part" / pn / pkg
    _seed_visual_assets(pkg_root, pn)
    client = TestClient(server.app)
    r1 = client.post("/api/library/intake/promote",
                     json=_default_body(revision="revA", part_package_id=pkg))
    assert r1.status_code == 200, r1.text
    rev_dir = intake_library / "parts" / pn / "revA"
    stale_glb = rev_dir / f"{pn}_colored.glb"
    stale_iso = rev_dir / f"{pn}_view_isometric.png"
    assert stale_glb.read_bytes() == b"glTF\x02\x00\x00\x00"

    # Drop a curated, non-managed file the wizard must preserve.
    curated = rev_dir / "operator_notes.txt"
    curated.write_text("keep these", encoding="utf-8")

    # Sidecar gets refreshed visuals (mimics post-enrich state)
    (pkg_root / "part" / f"{pn}_colored.glb").write_bytes(b"FRESH_GLB_BYTES")
    (pkg_root / "part" / f"{pn}_view_isometric.png").write_bytes(b"\x89PNG\r\n\x1a\nFRESH")

    # Second promote: SAME package id (no packageIdChangeAcknowledged
    # needed) + replaceManagedVisuals=true.
    body = _default_body(revision="revA", part_package_id=pkg,
                        overwrite_confirmed="revA")
    body["replaceManagedVisuals"] = True
    r2 = client.post("/api/library/intake/promote", json=body)
    assert r2.status_code == 200, r2.text

    # Managed visuals replaced byte-for-byte
    assert stale_glb.read_bytes() == b"FRESH_GLB_BYTES", \
        "stale GLB should have been deleted + replaced with the refreshed sidecar GLB"
    assert stale_iso.read_bytes() == b"\x89PNG\r\n\x1a\nFRESH", \
        "stale isometric PNG should have been replaced"
    # Non-managed curated file untouched
    assert curated.read_text(encoding="utf-8") == "keep these"


def test_preview_marks_visual_rows_UPDATE_when_replaceManagedVisuals_set(intake_library: Path):
    """When the wizard sends replaceManagedVisuals=true the preview's
    action table must show UPDATE rows for managed visual whitelist
    files that already exist in the per-rev (not SKIP). This is what
    tells the operator visually that re-running Promote will actually
    replace the just-enriched files instead of skipping them."""
    pn = "1099999"
    pkg = "deadbeef0002"
    pkg_root = intake_library / "_bridge_imports" / "part" / pn / pkg
    _seed_visual_assets(pkg_root, pn)
    # First promote so per-rev has the visuals
    client = TestClient(server.app)
    r1 = client.post("/api/library/intake/promote",
                     json=_default_body(revision="revA", part_package_id=pkg))
    assert r1.status_code == 200, r1.text

    # Preview the same revision again WITHOUT the flag -> visual rows
    # should report SKIP (default copy-if-not-exists semantics).
    body_no_flag = _default_body(revision="revA", part_package_id=pkg,
                                  overwrite_confirmed="revA")
    pr_no_flag = client.post("/api/library/intake/preview", json=body_no_flag).json()
    glb_rows_no_flag = [a for a in pr_no_flag["actions"]
                        if a["path"].endswith(f"{pn}_colored.glb")]
    assert glb_rows_no_flag, "expected a GLB action row in the preview"
    assert glb_rows_no_flag[0]["kind"] == "SKIP", \
        f"without the flag, managed visual rows should be SKIP (got {glb_rows_no_flag[0]['kind']})"

    # Now preview WITH the flag -> visual rows flip to UPDATE.
    body_with_flag = dict(body_no_flag)
    body_with_flag["replaceManagedVisuals"] = True
    pr_with_flag = client.post("/api/library/intake/preview", json=body_with_flag).json()
    glb_rows_with_flag = [a for a in pr_with_flag["actions"]
                          if a["path"].endswith(f"{pn}_colored.glb")]
    assert glb_rows_with_flag, "expected a GLB action row in the preview"
    assert glb_rows_with_flag[0]["kind"] == "UPDATE", \
        f"with replaceManagedVisuals=true, managed visual rows must be UPDATE (got {glb_rows_with_flag[0]['kind']})"
