"""Tests for Library Intake Wizard Step 3 — frontend + revisions endpoint.

Backend coverage:
- GET /api/library/revisions/{partNumber} (the only new endpoint Step 3
  introduces). Validates the response shape per docs/library-intake-
  wizard-plan.md §9.2 plus the two MVP additions
  (rootDrawingMapPresent + lastBridgePartPackageId) that auto-fill the
  wizard form so the operator does not have to paste a sha256 hash.

Frontend coverage:
- Static HTML markers verifying the wizard panel + entry button + step-
  flow IDs are present in the served index.html. This is a smoke check,
  not a behavioural test (a full browser-driven E2E is out of scope for
  this commit). The marker set is the minimum the JS IIFE depends on;
  if any of these drift the wizard will fail to wire up on page load.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterator

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402


# ── Fixtures ──────────────────────────────────────────────────────────


@pytest.fixture
def empty_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    library = tmp_path / "rev_lib"
    library.mkdir()
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    monkeypatch.setattr(server, "assembly_profiles", {}, raising=False)
    monkeypatch.setattr(server, "inspector", None)
    yield library


def _seed_revision(library: Path, pn: str, rev: str, *, with_manifest: bool = False) -> Path:
    """Drop a minimal parts/{pn}/{rev}/ directory with a handful of files."""
    rev_dir = library / "parts" / pn / rev
    rev_dir.mkdir(parents=True)
    (rev_dir / f"{pn}_drawing_map.json").write_text("{}", encoding="utf-8")
    (rev_dir / f"{pn}.json").write_text("{}", encoding="utf-8")
    if with_manifest:
        (rev_dir / "intake_manifest.json").write_text(json.dumps({
            "schemaVersion": "1.0.0",
            "partNumber":    pn,
            "revision":      rev,
            "promotedAtUtc": "2026-05-18T20:00:00.000Z",
            "promotedBy":    "test@host",
            "intakeMode":    "brand-new-part",
            "sourceDrawing": {"packageId": "dabc1234"},
            "sourcePart":    {"packageId": "pabc5678"},
        }), encoding="utf-8")
    return rev_dir


# ── /api/library/revisions/{partNumber} ────────────────────────────────


def test_revisions_endpoint_empty_library_returns_empty_list(empty_library: Path):
    """Brand-new part: no parts/{pn}/ folder yet -> empty revisions list,
    NOT 404. Wizard treats this as the normal first-revision flow."""
    client = TestClient(server.app)
    r = client.get("/api/library/revisions/1099999")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["partNumber"] == "1099999"
    assert body["revisions"] == []
    assert body["rootDrawingMapPresent"] is False
    assert body["lastBridgePartPackageId"] is None


def test_revisions_endpoint_lists_existing_revisions(empty_library: Path):
    _seed_revision(empty_library, "1099999", "revA")
    _seed_revision(empty_library, "1099999", "revB")
    client = TestClient(server.app)
    r = client.get("/api/library/revisions/1099999")
    body = r.json()
    names = [rev["name"] for rev in body["revisions"]]
    assert names == ["revA", "revB"]
    # paths are POSIX-style + library-relative for cross-platform display
    assert body["revisions"][0]["path"] == "parts/1099999/revA"
    assert body["revisions"][1]["path"] == "parts/1099999/revB"
    # fileCount reflects what's on disk
    assert all(rev["fileCount"] > 0 for rev in body["revisions"])


def test_revisions_endpoint_reads_intake_manifest_excerpt(empty_library: Path):
    _seed_revision(empty_library, "1099999", "revA", with_manifest=True)
    _seed_revision(empty_library, "1099999", "revB", with_manifest=False)
    client = TestClient(server.app)
    r = client.get("/api/library/revisions/1099999")
    by_name = {rev["name"]: rev for rev in r.json()["revisions"]}
    assert by_name["revA"]["intakeManifest"] is not None
    assert by_name["revA"]["intakeManifest"]["intakeMode"] == "brand-new-part"
    assert by_name["revA"]["intakeManifest"]["sourceDrawing"]["packageId"] == "dabc1234"
    # revB has no manifest -- excerpt is None
    assert by_name["revB"]["intakeManifest"] is None


def test_revisions_endpoint_returns_bridge_latest_package_id(empty_library: Path):
    bridge_dir = empty_library / "_bridge_imports" / "part" / "1099999"
    bridge_dir.mkdir(parents=True)
    (bridge_dir / "_latest.txt").write_text(
        "4c9d1ceb8991f127131e15c00aa944f5727ce763c8d20570baaec4ef66b25cb9\n",
        encoding="utf-8",
    )
    client = TestClient(server.app)
    body = client.get("/api/library/revisions/1099999").json()
    assert body["lastBridgePartPackageId"] == \
        "4c9d1ceb8991f127131e15c00aa944f5727ce763c8d20570baaec4ef66b25cb9"


def test_revisions_endpoint_root_drawing_map_flag(empty_library: Path):
    client = TestClient(server.app)
    # Before drawing map exists
    body = client.get("/api/library/revisions/1099999").json()
    assert body["rootDrawingMapPresent"] is False
    # After
    (empty_library / "1099999_drawing_map.json").write_text("{}", encoding="utf-8")
    body = client.get("/api/library/revisions/1099999").json()
    assert body["rootDrawingMapPresent"] is True


def test_revisions_endpoint_skips_non_rev_dirs(empty_library: Path):
    """Defensive: parts/{pn}/ may have stray non-rev directories
    (e.g. an `_archive/` folder). The wizard must skip them."""
    (empty_library / "parts" / "1099999" / "_archive").mkdir(parents=True)
    (empty_library / "parts" / "1099999" / "scratch").mkdir(parents=True)
    _seed_revision(empty_library, "1099999", "revA")
    client = TestClient(server.app)
    names = [rev["name"] for rev in client.get("/api/library/revisions/1099999").json()["revisions"]]
    assert names == ["revA"]


def test_revisions_endpoint_invalid_part_number_returns_400(empty_library: Path):
    client = TestClient(server.app)
    # `!!!` survives nothing after sanitise -> sanitize_part_number returns ""
    r = client.get("/api/library/revisions/!!!")
    assert r.status_code == 400


# ── Static HTML markers ───────────────────────────────────────────────


def test_served_html_contains_wizard_panel_dom_markers():
    """Wizard JS IIFE wires up DOM by ID; if any of these IDs drift the
    `if (!panel || !openBtn) return;` early-return fires silently."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        # DOM IDs the JS depends on
        'id="intakeWizardPanel"',
        'id="openIntakeWizardBtn"',
        'id="intakeWizardCloseBtn"',
        'id="intakeWizardStepNum"',
        'id="intakeWizardStepBar"',
        'id="intakeWizardBody"',
        'id="intakeWizardFooter"',
        # Endpoint URLs the IIFE calls
        '/api/library/revisions/',
        '/api/library/intake/preview',
        '/api/library/intake/promote',
        # Entry-button label so operators can find it
        '+ Add to Library',
        # Accessibility: title is real DOM text (screen reader)
        'Library Intake Wizard',
        # Theme tokens used by wizard CSS (must match the unified
        # light/dark theme system from main)
        'var(--present)',
        'var(--partial)',
        'var(--missing)',
    ]:
        assert marker in html, f"missing wizard marker: {marker!r}"


def test_served_html_does_not_break_step1_stub_surface():
    """Step 3 must NOT regress the Step 1 stub-aware surface
    (badge + banner + Inspect-button gate). Confirm those markers
    still appear in the same served HTML."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        # Step 1 picker badge wiring
        '_isIntakeStubProfile',
        '[INTAKE]',
        '_updateInspectButtonStubGate',
        # Step 1 backend gate the badge depends on
        'profile_incomplete',
    ]:
        assert marker in html, f"Step 1 marker regressed: {marker!r}"


# ── Stabilization-pass regression guards ──────────────────────────────


def test_served_html_wizard_initializes_after_dom_ready():
    """Regression for the 'wizard button does nothing on first click'
    smoke bug. The wizard panel HTML is positioned AFTER the script
    tag that runs the wizard IIFE -- without a DOMContentLoaded gate,
    document.getElementById('intakeWizardPanel') returns null at IIFE
    eval time and the early-return `if (!panel || !openBtn) return;`
    fires silently. Confirm the init-defer pattern is in the served
    HTML so the wizard wires up regardless of script vs. DOM ordering."""
    client = TestClient(server.app)
    html = client.get("/").text
    assert 'function initIntakeWizard()' in html, \
        "wizard init was inlined again -- needs to live inside initIntakeWizard()"
    assert "document.readyState === 'loading'" in html, \
        "readyState gate missing -- wizard will silently no-op if HTML loads first"
    assert "'DOMContentLoaded', initIntakeWizard" in html, \
        "DOMContentLoaded dispatch missing -- wizard will silently no-op"


def test_bridge_extract_uses_resolved_library_dir():
    """Regression for the 'worktree-local stub library' smoke bug.
    _bridge_extract_and_unpack was using Path('400S_Sorted_Library')
    which resolves against process CWD -- when uvicorn runs from a
    worktree under tmp/, the bridge wrote drawings into a fake
    library next to the worktree instead of the canonical one. Must
    use the resolved server.LIBRARY_DIR (which respects the multi-
    candidate scoring in _resolve_library_dir)."""
    import inspect
    src = inspect.getsource(server._bridge_extract_and_unpack)
    # Old buggy patterns must not return
    assert 'Path("400S_Sorted_Library")' not in src, \
        "bridge still uses CWD-relative Path('400S_Sorted_Library') -- " \
        "worktree-local library bug is back"
    assert "Path('400S_Sorted_Library')" not in src
    # New correct pattern present
    assert "library_root = LIBRARY_DIR" in src, \
        "bridge no longer pins library_root to the resolved LIBRARY_DIR"


def test_wizard_metadata_capture_helpers_present():
    """Regression for the 'intake_manifest has blank drawing metadata'
    smoke bug. The wizard must (a) cache the bridge response in
    window._lastBridgeExtractions, (b) pull from it via
    _autofillFromBridgeCache when the operator advances past Step 1,
    and (c) include the captured count fields in _intakeBody so they
    flow into preview/promote and into intake_manifest.json. Static
    checks here -- behavioural coverage is in
    test_intake_preview_promote.test_promote_carries_all_metadata_fields_into_manifest."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        # Cache write on bridge success
        'window._lastBridgeExtractions',
        # State fields the cache populates
        'drawingSheetCount:        null',
        'drawingViewCount:         null',
        'partFeatureCount:         null',
        # Auto-fill helper
        'function _autofillFromBridgeCache',
        '_autofillFromBridgeCache(pn)',
        # _intakeBody includes the new keys
        'out.drawingSheetCount',
        'out.drawingViewCount',
        'out.partFeatureCount',
        'out.partActiveConfiguration',
    ]:
        assert marker in html, f"wizard metadata wiring regressed: {marker!r}"
