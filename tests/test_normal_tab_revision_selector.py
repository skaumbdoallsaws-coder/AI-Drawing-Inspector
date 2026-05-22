"""Tests for the normal 3D Model tab revision selector.

Two surfaces:
1. Backend: /api/part-features/{pn} now accepts an optional ?revision=
   query and the agent context normalizer flattens part.revision so
   the HIGHLIGHT_REGIONS marker parser resolves against the visible
   revision.
2. Frontend (static guards): the served HTML contains the new DOM
   markers + endpoint URLs the normal-tab JS depends on, and the
   Compare-tab selectors stay untouched.
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _write_part_with_two_revisions(library: Path, pn: str) -> None:
    """Write a minimal library with rev A and rev B feature_colors so
    /api/part-features can resolve each revision separately."""
    for rev_letter, type_tag in (("A", "extrude"), ("B", "fillet")):
        rev_dir = library / "parts" / pn / f"rev{rev_letter}"
        rev_dir.mkdir(parents=True)
        (rev_dir / f"{pn}_feature_colors.json").write_text(json.dumps({
            "partNumber": pn,
            "revision":   rev_letter,
            "features": [
                {"cad_feature_id": f"{type_tag}_marker_{rev_letter.lower()}",
                 "glb_node_name": f"{type_tag}_marker_{rev_letter.lower()}",
                 "type": type_tag, "display_label": f"Rev-{rev_letter} marker"},
            ],
        }), encoding="utf-8")


@pytest.fixture
def revisioned_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    library = tmp_path / "lib"
    library.mkdir()
    _write_part_with_two_revisions(library, "1030099")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


# ---------------------------------------------------------------------------
# Backend: /api/part-features revision routing
# ---------------------------------------------------------------------------

def test_part_features_no_revision_falls_back_to_revA(revisioned_library: Path):
    """No ?revision= -> legacy revA-preferred behavior (backward compat
    for non-revisioned callers)."""
    client = TestClient(server.app)
    r = client.get("/api/part-features/1030099")
    assert r.status_code == 200, r.text
    body = r.json()
    feature_ids = {f.get("cad_feature_id") for f in body.get("features", [])}
    assert "extrude_marker_a" in feature_ids
    # Rev-B marker must NOT bleed in when no revision was requested.
    assert "fillet_marker_b" not in feature_ids


def test_part_features_with_revision_loads_that_rev(revisioned_library: Path):
    """?revision=B -> rev B file, NOT revA. Required so the normal 3D
    tab can switch between revisions without seeing stale feature IDs."""
    client = TestClient(server.app)
    r = client.get("/api/part-features/1030099", params={"revision": "B"})
    assert r.status_code == 200, r.text
    feature_ids = {f.get("cad_feature_id") for f in r.json().get("features", [])}
    assert "fillet_marker_b" in feature_ids
    assert "extrude_marker_a" not in feature_ids


def test_part_features_accepts_both_revB_and_B(revisioned_library: Path):
    """The frontend dropdown holds the bare letter (revs returned from
    /api/part-revisions strip the 'rev' prefix), but operators may also
    paste 'revB' into a URL. Both forms must work."""
    client = TestClient(server.app)
    bare = client.get("/api/part-features/1030099", params={"revision": "B"}).json()
    full = client.get("/api/part-features/1030099", params={"revision": "revB"}).json()
    assert bare == full


def test_part_features_missing_revision_returns_404(revisioned_library: Path):
    """Explicit ?revision=X for a rev that has no feature_colors.json
    must 404 instead of silently serving revA -- otherwise the wrong
    feature IDs land on the wrong on-screen GLB."""
    client = TestClient(server.app)
    r = client.get("/api/part-features/1030099", params={"revision": "Z"})
    assert r.status_code == 404
    assert "revision" in r.text.lower()


def test_part_features_invalid_revision_returns_400(revisioned_library: Path):
    """Garbage that sanitizes to empty -> 400 (not 500)."""
    client = TestClient(server.app)
    r = client.get("/api/part-features/1030099", params={"revision": "!!!"})
    assert r.status_code == 400


# ---------------------------------------------------------------------------
# Backend: normalize_agent_context flattens part.revision
# ---------------------------------------------------------------------------

def test_normalize_agent_context_flattens_part_revision():
    """The frontend now sends attachments.part.revision. The flatten
    pass must produce flat['revision'] so the HIGHLIGHT_REGIONS marker
    parser (which reads `(ctx or {}).get('revision')`) sees the right
    rev."""
    normalized = server.normalize_agent_context({
        "attachments": {
            "part": {"part_number": "1030099", "revision": "B"},
        }
    })
    flat = normalized["flat"]
    assert flat.get("part_number") == "1030099"
    assert flat.get("revision")    == "B"


def test_normalize_agent_context_no_revision_is_silent():
    """Missing or empty part.revision must NOT inject a falsy revision
    key -- downstream code distinguishes 'revision absent' from
    'revision provided'."""
    normalized = server.normalize_agent_context({
        "attachments": {"part": {"part_number": "1030099"}}
    })
    assert normalized["flat"].get("revision") is None


# ---------------------------------------------------------------------------
# Frontend static guards
# ---------------------------------------------------------------------------

def test_served_html_contains_normal_tab_revision_selector_markers():
    """Normal 3D Model tab revision selector DOM IDs + the helper
    functions the JS depends on. If any of these drift silently the
    selector goes missing and the user is stuck on revA again."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        # DOM IDs (assigned via JS, so the literal `id='...'` form
        # never appears in the served HTML -- the bare string check
        # is sufficient and matches both the assignment AND any
        # downstream document.getElementById() lookups).
        "normalTabRevisionBar",
        "normalTabRevisionSelect",
        # State field + initialization helper
        "state.activeRevision",
        "_initNormalTabActiveRevision",
        # URL helpers
        "_normalTabPartGlbUrl",
        "_normalTabFeaturesUrl",
        # Switch handler
        "_switchNormalTabRevision",
        # Revision-aware URLs the helpers emit
        "/api/part-glb-rev/",
        "/api/part-features/",
        # Endpoint that populates the dropdown options
        "/api/part-revisions/",
        # Agent context wiring -- revision flows to Sage
        "revision: state.activeRevision",
    ]:
        assert marker in html, f"missing normal-tab revision marker: {marker!r}"


def test_normal_tab_glb_loader_uses_revision_aware_url():
    """The single-model GLB loader must call _normalTabPartGlbUrl (which
    resolves to /api/part-glb-rev?revision=X when active) instead of
    hardcoding /api/part-glb. Guards against future refactors that
    accidentally bypass the helper."""
    client = TestClient(server.app)
    html = client.get("/").text
    # The loader.load(...) call inside _loadPartModel must go through
    # the helper so the active revision is honored.
    assert "loader.load(\n                _normalTabPartGlbUrl(pn)" in html \
        or "_normalTabPartGlbUrl(pn)" in html, \
        "_loadPartModel must route through _normalTabPartGlbUrl"


def test_normal_tab_feature_color_fetches_use_helper():
    """Both feature-color fetch sites (eager + on-tab-init) must route
    through _normalTabFeaturesUrl. If a refactor accidentally restores
    the hardcoded /api/part-features/${pn} URL the feature colors will
    stop tracking the revision switch."""
    client = TestClient(server.app)
    html = client.get("/").text
    # Count fetch sites that go through the helper. Expect at least 2
    # (the eager post-profile-load fetch + the on-3D-tab-init fetch).
    helper_call_count = html.count("_normalTabFeaturesUrl(")
    assert helper_call_count >= 3, \
        f"expected >=3 _normalTabFeaturesUrl call sites (definition + 2 fetches), got {helper_call_count}"


def test_compare_tab_selectors_untouched():
    """Regression guard: the Compare subtab has its own revision
    selectors and state (partDiffState.activeRevA / B, DOM IDs
    partCompareRevASelect / BSelect). This change must not rename or
    remove any of them."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        "partCompareRevASelect",
        "partCompareRevBSelect",
        "partDiffState.activeRevA",
        "partDiffState.activeRevB",
        "_renderPartCompareSubtab",
        "_destroyPartDiffViewers",
    ]:
        assert marker in html, \
            f"Compare-tab marker regressed: {marker!r} -- the normal-tab " \
            f"revision selector change must not touch Compare wiring."


def test_legacy_part_glb_endpoint_unchanged():
    """/api/part-glb/{pn} (without rev) must keep its legacy behavior
    so non-revisioned parts still work. We can't reach the engine here
    without a populated library, but we CAN confirm the route is still
    declared in source and that the new revision-aware URL helper
    falls back to it when state.activeRevision is null."""
    import inspect
    src = inspect.getsource(server)
    assert '@app.get("/api/part-glb/{part_number}")' in src, \
        "legacy /api/part-glb route must stay registered for non-revisioned parts"

    client = TestClient(server.app)
    html = client.get("/").text
    # Helper must fall back to legacy URL when no revision is active.
    assert "/api/part-glb/${encodeURIComponent(pn)}" in html, \
        "_normalTabPartGlbUrl fallback to /api/part-glb is missing"
