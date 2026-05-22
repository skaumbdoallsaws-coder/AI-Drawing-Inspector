"""Tests for the Semantic Region Curator MVP.

Covers:
- PUT /api/part-semantic-regions/{partNumber}?revision=X happy path
  (round-trip preserves schema 1.3.0+ fields and any unknown future
  fields the operator/UI might start sending)
- Validation: duplicate glbNode across regions, unknown glbNode,
  unknown cadFeatureId, partNumber/revision mismatch
- Atomic write: a failed validation does not modify the on-disk file
- Existing POST /draft preservation still works for reviewed=true
  regions persisted via the curator

The fixture reuses the same synthetic GLB + feature_colors layout
the existing semantic-regions tests use so the round-trip exercises
the real path.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Iterator, List, Tuple

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from ai_inspector.semantic_regions import (
    build_draft_regions,
    semantic_regions_path,
    write_semantic_regions,
)

# Reuse the same synthetic GLB writer + aircraft fixture the broader
# semantic_regions suite uses so the curator tests exercise the same
# heuristic + file shapes operators see in production.
sys.path.insert(0, str(REPO_ROOT / "tests"))
import test_semantic_regions as _sr_tests  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def aircraft_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Library with a single revisioned aircraft part (1030099 revA),
    synthetic GLB on disk, feature_colors.json populated. LIBRARY_DIR
    is monkeypatched so server.library_path() resolves here."""
    library = tmp_path / "lib"
    pn, rev = "1030099", "revA"
    rev_dir = library / "parts" / pn / rev
    rev_dir.mkdir(parents=True)
    _sr_tests._write_synthetic_glb(rev_dir / f"{pn}_colored.glb",
                                   _sr_tests._aircraft_fixture())
    (rev_dir / f"{pn}_feature_colors.json").write_text(json.dumps({
        "partNumber": pn,
        "features": [
            {
                "cad_feature_id": n,
                "glb_node_name":  n,
                "sw_name":        n.replace("_", " ").title(),
                "type":           n.split("_", 1)[0],
                "display_label":  n.replace("_", " ").title(),
            }
            for n, *_ in _sr_tests._aircraft_fixture()
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


@pytest.fixture
def aircraft_library_with_draft(aircraft_library: Path) -> Path:
    """Bootstraps the draft regions file so PUT has something to
    round-trip against. Returns the library root path."""
    pn, rev = "1030099", "revA"
    doc = build_draft_regions(aircraft_library, pn, rev)
    write_semantic_regions(aircraft_library, pn, rev, doc)
    return aircraft_library


def _read_persisted(library: Path, pn: str, rev: str) -> dict:
    return json.loads(semantic_regions_path(library, pn, rev).read_text(encoding="utf-8-sig"))


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_PUT_round_trip_persists_operator_edits(aircraft_library_with_draft: Path):
    """The canonical curator flow: GET the draft, mutate label +
    aliases + reviewed on one region, PUT the full doc back. The
    file on disk must reflect the edits exactly and keep all the
    untouched regions verbatim."""
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)

    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()
    assert "regions" in doc and doc["regions"], doc

    edited_regions = []
    for r in doc["regions"]:
        if r["regionId"] == "top_wing":
            r = {**r,
                 "label":    "Main upper wing",
                 "aliases":  list(r.get("aliases", [])) + ["main upper wing"],
                 "reviewed": True}
        edited_regions.append(r)

    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={
            "partNumber": pn,
            "revision":   rev,
            "regions":    edited_regions,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["partNumber"] == pn
    assert body["regionCount"] == len(edited_regions)

    persisted = _read_persisted(aircraft_library_with_draft, pn, rev)
    top_wing = next(r for r in persisted["regions"] if r["regionId"] == "top_wing")
    assert top_wing["label"]    == "Main upper wing"
    assert top_wing["reviewed"] is True
    assert "main upper wing" in top_wing["aliases"]


def test_PUT_preserves_unknown_future_fields_verbatim(aircraft_library_with_draft: Path):
    """Operator/UI may start sending future scaffolding fields
    (placementSurfaces extensions, new editReadiness states, etc.)
    that the backend doesn't yet understand. They MUST round-trip
    untouched -- the curator contract is intentionally permissive
    so schema evolution never blocks on a server deploy."""
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)

    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()
    regions = doc["regions"]
    # Inject a never-seen-before field at multiple nesting levels.
    regions[0]["operatorNotes"] = "Picked this up from a curator meeting on 2026-05-22"
    regions[0]["futureField"] = {"foo": "bar", "nested": [1, 2, 3]}
    regions[0].setdefault("placementSurfaces", []).append({
        "newSurfaceKind": "experimental-fillet-target",
        "anchor": "test-anchor",
    })

    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={"regions": regions},
    )
    assert r.status_code == 200, r.text

    persisted = _read_persisted(aircraft_library_with_draft, pn, rev)
    r0 = persisted["regions"][0]
    assert r0["operatorNotes"].startswith("Picked this up")
    assert r0["futureField"]   == {"foo": "bar", "nested": [1, 2, 3]}
    assert r0["placementSurfaces"][-1]["newSurfaceKind"] == "experimental-fillet-target"


def test_PUT_canonicalises_top_level_metadata_from_url(aircraft_library_with_draft: Path):
    """The persisted file must always be self-describing: partNumber
    + revision get set from the URL even when the body omits them so
    a half-filled curator request can't desync the doc from its
    location on disk."""
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)
    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()

    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={"regions": doc["regions"]},  # NO partNumber / revision in body
    )
    assert r.status_code == 200, r.text
    persisted = _read_persisted(aircraft_library_with_draft, pn, rev)
    assert persisted["partNumber"] == pn
    assert persisted["revision"]   == rev
    assert persisted["schemaVersion"]  # filled from server default


def test_PUT_allows_operator_moving_glb_node_between_regions(aircraft_library_with_draft: Path):
    """The curator's main correction action is moving one GLB/CAD node
    from an incorrect semantic region into the correct one. This must
    pass validation as long as the node exists and is not duplicated."""
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)
    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()

    top = next(r for r in doc["regions"] if r["regionId"] == "top_wing")
    lower = next(r for r in doc["regions"] if r["regionId"] == "lower_wing")
    moved = lower["visualTargets"]["glbNodes"][0]

    lower["visualTargets"]["glbNodes"] = [
        n for n in lower["visualTargets"]["glbNodes"] if n != moved
    ]
    lower["glbNodes"] = list(lower["visualTargets"]["glbNodes"])
    lower["cadTargets"]["cadFeatureIds"] = [
        n for n in lower["cadTargets"]["cadFeatureIds"] if n != moved
    ]

    top["visualTargets"]["glbNodes"] = list(top["visualTargets"]["glbNodes"]) + [moved]
    top["glbNodes"] = list(top["visualTargets"]["glbNodes"])
    top["cadTargets"]["cadFeatureIds"] = list(top["cadTargets"]["cadFeatureIds"]) + [moved]

    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={"regions": doc["regions"]},
    )
    assert r.status_code == 200, r.text

    persisted = _read_persisted(aircraft_library_with_draft, pn, rev)
    top_after = next(r for r in persisted["regions"] if r["regionId"] == "top_wing")
    lower_after = next(r for r in persisted["regions"] if r["regionId"] == "lower_wing")
    assert moved in top_after["visualTargets"]["glbNodes"]
    assert moved not in lower_after["visualTargets"]["glbNodes"]


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def test_PUT_rejects_duplicate_glbNode_across_regions(aircraft_library_with_draft: Path):
    """Two regions claiming the same glbNode is an operator bug
    (probably a botched merge/split). Reject with 400 and surface
    a specific error so the curator can highlight the offending
    nodes."""
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)
    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()

    # Take a node from top_wing and also put it into lower_wing.
    top_wing = next(r for r in doc["regions"] if r["regionId"] == "top_wing")
    stolen = top_wing["visualTargets"]["glbNodes"][0]
    for r in doc["regions"]:
        if r["regionId"] == "lower_wing":
            r["visualTargets"]["glbNodes"] = list(r["visualTargets"]["glbNodes"]) + [stolen]

    persisted_before = _read_persisted(aircraft_library_with_draft, pn, rev)
    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={"regions": doc["regions"]},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    msg = json.dumps(body)
    assert "more than one region" in msg or "at most one region" in msg, body
    assert stolen in msg
    # Atomic: on-disk file must NOT have been mutated by the rejected write.
    persisted_after = _read_persisted(aircraft_library_with_draft, pn, rev)
    assert persisted_after == persisted_before


def test_PUT_rejects_unknown_glbNode(aircraft_library_with_draft: Path):
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)
    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()
    top_wing = next(r for r in doc["regions"] if r["regionId"] == "top_wing")
    top_wing["visualTargets"]["glbNodes"] = ["this_node_does_not_exist_xyzzy"]

    persisted_before = _read_persisted(aircraft_library_with_draft, pn, rev)
    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={"regions": doc["regions"]},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert "does not exist in the current revision GLB" in json.dumps(body)
    assert "this_node_does_not_exist_xyzzy" in json.dumps(body)
    assert _read_persisted(aircraft_library_with_draft, pn, rev) == persisted_before


def test_PUT_rejects_unknown_cadFeatureId(aircraft_library_with_draft: Path):
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)
    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()
    top_wing = next(r for r in doc["regions"] if r["regionId"] == "top_wing")
    top_wing["cadTargets"]["cadFeatureIds"] = ["ghost_cad_id"]

    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={"regions": doc["regions"]},
    )
    assert r.status_code == 400, r.text
    body = r.json()
    assert "feature_colors.json" in json.dumps(body)
    assert "ghost_cad_id" in json.dumps(body)


def test_PUT_rejects_partNumber_mismatch(aircraft_library_with_draft: Path):
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)
    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()

    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={
            "partNumber": "9999999",   # WRONG
            "revision":   rev,
            "regions":    doc["regions"],
        },
    )
    assert r.status_code == 400, r.text
    assert "does not match URL part" in r.text


def test_PUT_rejects_revision_mismatch(aircraft_library_with_draft: Path):
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)
    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()
    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={
            "partNumber": pn,
            "revision":   "Q",      # WRONG -- not the URL rev
            "regions":    doc["regions"],
        },
    )
    assert r.status_code == 400, r.text
    assert "does not match URL revision" in r.text


def test_PUT_returns_404_when_GLB_missing(aircraft_library_with_draft: Path):
    """A part rev whose colored GLB doesn't exist can't be validated
    (we can't compute the authoritative glbNode set). Return 404 with
    a remediation hint instead of silently writing an unvalidated
    file."""
    pn, rev = "1030099", "revA"
    # Remove the GLB so validation can't compute its node set.
    glb = aircraft_library_with_draft / "parts" / pn / rev / f"{pn}_colored.glb"
    glb.unlink()

    client = TestClient(server.app)
    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={"regions": []},
    )
    assert r.status_code == 404, r.text
    assert "colored GLB is missing" in r.text


# ---------------------------------------------------------------------------
# reviewed=true survives a subsequent POST /draft (existing preservation
# path -- the curator just sets the flag, it doesn't own the rebuild
# logic)
# ---------------------------------------------------------------------------

def test_PUT_reviewed_true_survives_subsequent_POST_draft(aircraft_library_with_draft: Path):
    """An operator locks top_wing via PUT (reviewed=true with a custom
    label), then a downstream caller re-runs POST /draft. The locked
    region must carry over verbatim because the heuristic builder
    already preserves reviewed=true. This is end-to-end coverage that
    the curator's lock survives a redraft, not just a builder unit
    test."""
    pn, rev = "1030099", "revA"
    client = TestClient(server.app)

    doc = client.get(f"/api/part-semantic-regions/{pn}", params={"revision": rev}).json()
    regions = doc["regions"]
    for r_ in regions:
        if r_["regionId"] == "top_wing":
            r_["label"]    = "OPERATOR-LOCKED LABEL"
            r_["reviewed"] = True

    r = client.put(
        f"/api/part-semantic-regions/{pn}",
        params={"revision": rev},
        json={"regions": regions},
    )
    assert r.status_code == 200, r.text

    # Re-run the heuristic draft. The locked region should carry through.
    rd = client.post(
        f"/api/part-semantic-regions/{pn}/draft",
        json={"revision": rev},
    )
    assert rd.status_code == 200, rd.text
    redraft = rd.json()
    top_wing = next(r for r in redraft["regions"] if r["regionId"] == "top_wing")
    assert top_wing["reviewed"] is True
    assert top_wing["label"]    == "OPERATOR-LOCKED LABEL"


# ---------------------------------------------------------------------------
# Existing route surface preserved
# ---------------------------------------------------------------------------

def test_existing_GET_and_POST_routes_still_registered():
    """Regression: adding PUT must not delete the existing read /
    draft / resolve handlers."""
    paths_methods = {(r.path, frozenset(getattr(r, "methods", set()) or set()))
                     for r in server.app.routes}
    required = [
        ("/api/part-semantic-regions/{partNumber}",          "GET"),
        ("/api/part-semantic-regions/{partNumber}",          "PUT"),
        ("/api/part-semantic-regions/{partNumber}/draft",    "POST"),
        ("/api/part-semantic-regions/{partNumber}/resolve",  "GET"),
    ]
    for path, method in required:
        assert any(p == path and method in methods for p, methods in paths_methods), \
            f"missing route: {method} {path}"


# ---------------------------------------------------------------------------
# Frontend static guards -- the curator JS is wired by string-matched IDs
# and function names. If any of these drift the curator silently goes
# missing or stops responding to clicks.
# ---------------------------------------------------------------------------

def test_served_html_contains_regions_curator_markers():
    """Regions sub-tab DOM ids + the helper functions the click /
    save / re-draft / highlight handlers depend on. If any of these
    drift the curator silently no-ops -- there is no other test that
    catches a renamed function name in the served HTML."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        # Sub-tab is added to the existing bar
        "{ id: 'regions', label: 'Regions' }",
        # The in-viewport sub-tab bar is hidden; the ribbon is the visible switcher.
        "['3dmodel','compare','regions']",
        # Branching in the renderer
        "_renderRegionsCuratorSubtab",
        # Toolbar DOM IDs
        "regionsCuratorRoot",
        "regionsCuratorToolbar",
        "regionsCuratorList",
        "regionsCuratorSaveBtn",
        "regionsCuratorRedraftBtn",
        "regionsCuratorDirtyBadge",
        # Curator state + lifecycle helpers
        "regionsCuratorState",
        "nodeCatalog",
        "nodeOrder",
        "_regionsCuratorLoad",
        "_regionsCuratorSave",
        "_regionsCuratorRedraft",
        "_regionsCuratorMoveNodeToRegion",
        "_regionsCuratorSetRegionNodes",
        "_regionsCuratorRefreshNodeCatalog",
        "_regionsCuratorSelectRegion",
        "_renderRegionsCuratorListIfMounted",
        # Edit-field class hooks (kept stable for later e2e tests)
        "regions-curator-card",
        "regions-curator-label-input",
        "regions-curator-aliases-input",
        "regions-curator-node-membership",
        "regions-curator-node-move-select",
        "regions-curator-reviewed-checkbox",
    ]:
        assert marker in html, f"missing regions-curator marker: {marker!r}"


def test_served_html_curator_uses_correct_endpoint_urls():
    """The curator must call the correct REST surface: GET to load,
    PUT to save the full document, POST /draft to regenerate. If
    these URLs drift the curator hits the wrong handler."""
    client = TestClient(server.app)
    html = client.get("/").text
    # Load + save + re-draft URLs
    assert "`/api/part-semantic-regions/${encodeURIComponent(pn)}?revision=${encodeURIComponent(revision)}`" in html, \
        "curator load URL drift"
    assert "method: 'PUT'" in html, "curator save must use PUT"
    assert "/api/part-semantic-regions/${encodeURIComponent(regionsCuratorState.pn)}/draft" in html, \
        "curator re-draft URL drift"


def test_served_html_curator_does_not_regress_compare_subtab():
    """Adding the Regions sub-tab must not remove / rename the Compare
    sub-tab. partDiffState.activeRevA/B + partCompareRev[A|B]Select
    are the load-bearing identifiers for the existing flow."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        "{ id: 'compare', label: 'Compare' }",
        "_renderPartCompareSubtab",
        "partCompareRevASelect",
        "partCompareRevBSelect",
        "partDiffState.activeRevA",
        "partDiffState.activeRevB",
    ]:
        assert marker in html, f"Compare sub-tab marker regressed: {marker!r}"


def test_served_html_curator_clears_highlights_on_subtab_leave():
    """Switching away from Regions must clear any region-driven 3D
    highlights so the next view does not inherit them. Guards the
    `if (prev === 'regions' && ... clearFeatureHighlights())` block
    in the sub-tab click handler."""
    client = TestClient(server.app)
    html = client.get("/").text
    assert "prev === 'regions'" in html, \
        "curator must detect leaving the Regions sub-tab"
    assert "clearFeatureHighlights()" in html, \
        "curator must clear highlights when leaving Regions"


def test_served_html_curator_select_uses_apply_feature_highlight():
    """Clicking a region in the curator must route through the existing
    applyFeatureHighlight pipeline so the 3D viewer reacts the same
    way it does for agent-driven and feature-explorer-driven highlights."""
    client = TestClient(server.app)
    html = client.get("/").text
    assert "applyFeatureHighlight(cleanIds)" in html, \
        "_regionsCuratorSelectRegion must call applyFeatureHighlight"


def test_served_html_curator_replays_highlight_after_glb_load_and_input_focus():
    """Region highlighting must not depend on clicking empty card
    chrome. Operators naturally click the editable label/alias fields,
    and that must still preview the selected region. If the model is
    still loading, the selected IDs are replayed after _buildFeatureMeshMap
    finishes."""
    client = TestClient(server.app)
    html = client.get("/").text
    for marker in [
        "pendingHighlightIds",
        "function _regionsCuratorApplyHighlightIds",
        "function _regionsCuratorPreviewRegion",
        "labelInput.addEventListener('focus', () => _regionsCuratorPreviewRegion(region))",
        "aliasInput.addEventListener('focus', () => _regionsCuratorPreviewRegion(region))",
        "reviewedCb.addEventListener('focus', () => _regionsCuratorPreviewRegion(region))",
        "_regionsCuratorApplyHighlightIds(regionsCuratorState.pendingHighlightIds)",
    ]:
        assert marker in html, f"missing curator highlight replay marker: {marker!r}"
