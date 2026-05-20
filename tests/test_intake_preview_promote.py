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
