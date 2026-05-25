"""Tests for the Feature Intent Map v1.

Covers:
- Builder produces a physical-language entry for the propeller's
  Boss-Extrude1 with depth1_mm -> "blade thickness".
- Pattern/mirror features are classified as propagation, not edit
  targets.
- reviewed=true entries survive a re-draft (curator preservation).
- The /draft + GET HTTP endpoints round-trip the map.
- Sage's compare-answer rendering uses physical language when the
  intent map exists and falls back to the legacy technical wording
  when it doesn't.
- A "technical" query appends the SolidWorks-name + parameter sentence.
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
from ai_inspector.feature_intent import (
    SCHEMA_VERSION,
    build_draft_intent_map,
    feature_intent_map_path,
    load_feature_intent_map,
    lookup_feature_intent,
    intent_entry_physical_phrase_for_param,
    write_feature_intent_map,
)
from ai_inspector.semantic_regions import (
    build_draft_regions,
    write_semantic_regions,
)

sys.path.insert(0, str(REPO_ROOT / "tests"))
import test_semantic_regions as _sr_tests  # noqa: E402

PN = "1030099"
REV = "revA"


# ---------------------------------------------------------------------------
# Fixture: synthetic aircraft library with feature_colors + semantic regions
# ---------------------------------------------------------------------------

@pytest.fixture
def aircraft_library_with_regions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Aircraft library populated with GLB + feature_colors +
    semantic_regions so the intent-map builder has every input it
    needs. The synthetic fixture maps each cad_feature_id to a
    title-cased sw_name (e.g. ice_boss_extrude1 -> "Ice Boss Extrude1")
    -- close enough to the production form for the intent rules to
    fire."""
    library = tmp_path / "lib"
    rev_dir = library / "parts" / PN / REV
    rev_dir.mkdir(parents=True)
    _sr_tests._write_synthetic_glb(rev_dir / f"{PN}_colored.glb",
                                   _sr_tests._aircraft_fixture())
    (rev_dir / f"{PN}_feature_colors.json").write_text(json.dumps({
        "partNumber": PN,
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
    # Generate the semantic regions doc so the intent builder can
    # tie features to region labels.
    regions_doc = build_draft_regions(library, PN, REV)
    write_semantic_regions(library, PN, REV, regions_doc)
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------

def test_builder_classifies_propeller_boss_extrude_with_blade_thickness_control(
    aircraft_library_with_regions: Path,
):
    """Per spec test 1: draft map for the synthetic aircraft creates
    a propeller Boss-Extrude entry with depth1_mm -> "blade thickness"."""
    doc = build_draft_intent_map(aircraft_library_with_regions, PN, REV)
    assert doc["schemaVersion"] == SCHEMA_VERSION
    boss = next(
        e for e in doc["features"]
        if e["cadFeatureId"] == "ice_boss_extrude1"
    )
    assert boss["editRole"] == "primary_edit_target"
    assert boss["regionId"] == "propeller", \
        f"expected propeller region, got {boss['regionId']!r}"
    # The control list contains exactly one depth1_mm entry whose
    # displayName reads "blade thickness" -- the demo's load-bearing
    # phrase.
    controls = boss["controls"]
    assert len(controls) == 1, controls
    assert controls[0]["parameter"]   == "depth1_mm"
    assert controls[0]["displayName"] == "blade thickness"
    assert controls[0]["units"]       == "mm"


def test_builder_classifies_pattern_features_as_propagation(
    aircraft_library_with_regions: Path,
):
    """Per spec test 2: cirpattern1 must be propagation, never an
    edit target."""
    doc = build_draft_intent_map(aircraft_library_with_regions, PN, REV)
    cirp = next(e for e in doc["features"] if e["cadFeatureId"] == "cirpattern1")
    assert cirp["editRole"] == "propagation"
    assert cirp["controls"] == []


def test_builder_includes_cirpattern_in_downstream_of_boss_extrude(
    aircraft_library_with_regions: Path,
):
    """The propeller Boss-Extrude's downstreamFeatures should name
    the pattern feature in the same region so a future executor
    knows the change will fan out."""
    doc = build_draft_intent_map(aircraft_library_with_regions, PN, REV)
    boss = next(e for e in doc["features"] if e["cadFeatureId"] == "ice_boss_extrude1")
    assert "cirpattern1" in (boss.get("downstreamFeatures") or [])


def test_builder_classifies_surface_features_as_reference(
    aircraft_library_with_regions: Path,
):
    """planarsurface_*, extrurefsurface_* etc must be reference --
    apply paths must never auto-target them."""
    doc = build_draft_intent_map(aircraft_library_with_regions, PN, REV)
    surf = next(
        e for e in doc["features"]
        if e["cadFeatureId"] == "planarsurface_top_wing"
    )
    assert surf["editRole"] == "reference"
    assert surf["controls"] == []


def test_builder_preserves_reviewed_true_entries_on_redraft(
    aircraft_library_with_regions: Path,
):
    """Per spec test 3: reviewed=true entries survive verbatim across
    re-drafts (operator's curation is sticky)."""
    first = build_draft_intent_map(aircraft_library_with_regions, PN, REV)
    # Mutate the propeller boss and lock it.
    for e in first["features"]:
        if e["cadFeatureId"] == "ice_boss_extrude1":
            e["physicalName"] = "OPERATOR-CURATED PROP BLADE"
            e["reviewed"]     = True
            e["controls"]     = [{
                "parameter":       "depth1_mm",
                "displayName":     "operator's bespoke blade thickness",
                "units":           "mm",
                "physicalMeaning": "Curated wording overrides the heuristic.",
            }]
            break
    write_feature_intent_map(aircraft_library_with_regions, PN, REV, first)

    second = build_draft_intent_map(aircraft_library_with_regions, PN, REV)
    boss = next(e for e in second["features"] if e["cadFeatureId"] == "ice_boss_extrude1")
    assert boss["reviewed"]     is True
    assert boss["physicalName"] == "OPERATOR-CURATED PROP BLADE"
    assert boss["controls"][0]["displayName"] == "operator's bespoke blade thickness"
    # Non-curated entries still get regenerated -- only the reviewed
    # entry is preserved verbatim.
    cirp = next(e for e in second["features"] if e["cadFeatureId"] == "cirpattern1")
    assert cirp["reviewed"] is False


def test_lookup_feature_intent_returns_entry_when_map_exists(
    aircraft_library_with_regions: Path,
):
    """lookup helper returns None when the map is absent (current
    state) and the matching entry once the map is generated."""
    assert lookup_feature_intent(aircraft_library_with_regions, PN, REV, "ice_boss_extrude1") is None
    doc = build_draft_intent_map(aircraft_library_with_regions, PN, REV)
    write_feature_intent_map(aircraft_library_with_regions, PN, REV, doc)
    hit = lookup_feature_intent(aircraft_library_with_regions, PN, REV, "ice_boss_extrude1")
    assert hit is not None
    assert hit["editRole"] == "primary_edit_target"


def test_intent_entry_physical_phrase_for_param_renders_propeller_sentence():
    """Pure renderer -- the spec's load-bearing sentence."""
    entry = {
        "cadFeatureId":  "ice_boss_extrude1",
        "regionLabel":   "Propeller",
        "controls": [{
            "parameter":   "depth1_mm",
            "displayName": "blade thickness",
            "units":       "mm",
        }],
    }
    phrase = intent_entry_physical_phrase_for_param(entry, "depth1_mm", 0.5, 5.5)
    assert phrase == "The propeller blade thickness increased from 0.5 mm to 5.5 mm."


def test_intent_entry_physical_phrase_returns_none_when_param_not_in_controls():
    entry = {"regionLabel": "Propeller", "controls": [
        {"parameter": "depth1_mm", "displayName": "blade thickness", "units": "mm"},
    ]}
    assert intent_entry_physical_phrase_for_param(entry, "diameter_mm", 1.0, 2.0) is None


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

def test_GET_part_feature_intent_404_when_absent(aircraft_library_with_regions: Path):
    client = TestClient(server.app)
    r = client.get(f"/api/part-feature-intent/{PN}", params={"revision": "A"})
    assert r.status_code == 404
    body = r.json()
    assert "/draft" in body["detail"]


def test_POST_draft_creates_file_and_GET_returns_it(aircraft_library_with_regions: Path):
    client = TestClient(server.app)
    r = client.post(f"/api/part-feature-intent/{PN}/draft", json={"revision": "A"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["schemaVersion"] == SCHEMA_VERSION
    assert body["featureCount"] >= 1

    # Round-trip via GET.
    rg = client.get(f"/api/part-feature-intent/{PN}", params={"revision": "A"})
    assert rg.status_code == 200, rg.text
    doc = rg.json()
    assert doc["partNumber"] == PN
    assert doc["revision"]   == REV
    assert any(f["cadFeatureId"] == "ice_boss_extrude1" for f in doc["features"])

    p = feature_intent_map_path(aircraft_library_with_regions, PN, REV)
    assert p.exists()


def test_POST_draft_404_when_feature_colors_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """No feature_colors.json -> POST /draft returns 404 with a
    remediation hint that points the operator at Enrich Visuals."""
    library = tmp_path / "lib"
    rev_dir = library / "parts" / PN / REV
    rev_dir.mkdir(parents=True)
    # Minimal GLB so the rev dir exists at all, but NO feature_colors.
    _sr_tests._write_synthetic_glb(rev_dir / f"{PN}_colored.glb",
                                   _sr_tests._aircraft_fixture())
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    client = TestClient(server.app)
    r = client.post(f"/api/part-feature-intent/{PN}/draft", json={"revision": "A"})
    assert r.status_code == 404, r.text
    assert "feature_colors" in r.text


def test_POST_draft_accepts_both_revA_and_A(aircraft_library_with_regions: Path):
    client = TestClient(server.app)
    a = client.post(f"/api/part-feature-intent/{PN}/draft", json={"revision": "A"})
    b = client.post(f"/api/part-feature-intent/{PN}/draft", json={"revision": "revA"})
    assert a.status_code == 200
    assert b.status_code == 200
    assert a.json()["revision"] == b.json()["revision"] == REV


# ---------------------------------------------------------------------------
# Sage compare-answer integration -- direct unit test on the formatter
# ---------------------------------------------------------------------------
# Driving the full agent_chat path requires a stubbed Anthropic + a
# library with two on-disk revisions wired into the diff endpoint;
# the formatter is the load-bearing piece and we test it directly
# here with the same intent_entry shape the runtime produces.

def test_format_summary_uses_physical_language_when_intent_entry_present():
    entry = {
        "cadFeatureId": "ice_boss_extrude1",
        "regionLabel":  "Propeller",
        "controls": [{
            "parameter":   "depth1_mm",
            "displayName": "blade thickness",
            "units":       "mm",
        }],
    }
    changes = {"parameters": {"depth1_mm": {"old": 0.5, "new": 5.5}}}
    # include_technical=False -> physical sentence only.
    out = server._format_feature_change_summary(
        "Boss-Extrude1", changes, intent_entry=entry, include_technical=False)
    assert out == "The propeller blade thickness increased from 0.5 mm to 5.5 mm"


def test_format_summary_appends_technical_line_when_requested():
    entry = {
        "regionLabel": "Propeller",
        "controls": [{
            "parameter":   "depth1_mm",
            "displayName": "blade thickness",
            "units":       "mm",
        }],
    }
    changes = {"parameters": {"depth1_mm": {"old": 0.5, "new": 5.5}}}
    out = server._format_feature_change_summary(
        "Boss-Extrude1", changes, intent_entry=entry, include_technical=True)
    # Physical first, technical after.
    assert "blade thickness increased from 0.5 mm to 5.5 mm" in out
    assert "Technically, Boss-Extrude1" in out
    assert "depth1_mm: 0.5 mm -> 5.5 mm" in out


def test_format_summary_falls_back_to_technical_when_no_intent_entry():
    """Missing intent map -> legacy wording preserved verbatim. This
    is the spec's "missing map falls back to current behavior" test."""
    changes = {"parameters": {"depth1_mm": {"old": 0.5, "new": 5.5}}}
    out = server._format_feature_change_summary("Boss-Extrude1", changes)
    # Legacy format -- "{label} changed {param}: {old} mm -> {new} mm ({delta} mm)"
    assert out.startswith("Boss-Extrude1 changed ")
    assert "depth1_mm: 0.5 mm -> 5.5 mm" in out


def test_format_summary_falls_back_when_intent_has_no_matching_control():
    """Intent entry exists but doesn't carry the changed parameter
    -> technical wording, not a malformed half-sentence."""
    entry = {
        "regionLabel": "Propeller",
        "controls": [{
            "parameter":   "diameter_mm",
            "displayName": "blade diameter",
            "units":       "mm",
        }],
    }
    changes = {"parameters": {"depth1_mm": {"old": 0.5, "new": 5.5}}}
    out = server._format_feature_change_summary(
        "Boss-Extrude1", changes, intent_entry=entry, include_technical=True)
    # Physical phrase was None, so legacy "{label} changed ..." kicks in.
    assert out.startswith("Boss-Extrude1 changed ")


def test_is_technical_drilldown_message_detects_solidworks_and_parameter_keywords():
    assert server._is_technical_drilldown_message("Compare Rev D and Rev E. What changed in SolidWorks?") is True
    assert server._is_technical_drilldown_message("Show me the exact parameter name") is True
    assert server._is_technical_drilldown_message("Compare Rev D and Rev E. What changed in the propeller?") is False


# ---------------------------------------------------------------------------
# Auto-draft: POST /api/part-semantic-regions/{pn}/draft must ALSO produce
# the feature intent map for the same pn/rev. The two sidecars are
# operationally siblings; an operator that just drafted regions expects
# the intent map to land at the same time without a second click.
# ---------------------------------------------------------------------------

@pytest.fixture
def aircraft_library_no_regions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """GLB + feature_colors only -- no semantic_regions doc on disk.
    Used so POST /api/part-semantic-regions/{pn}/draft starts from
    the clean state the auto-draft path is meant to handle."""
    library = tmp_path / "lib"
    rev_dir = library / "parts" / PN / REV
    rev_dir.mkdir(parents=True)
    _sr_tests._write_synthetic_glb(rev_dir / f"{PN}_colored.glb",
                                   _sr_tests._aircraft_fixture())
    (rev_dir / f"{PN}_feature_colors.json").write_text(json.dumps({
        "partNumber": PN,
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
def aircraft_library_no_feature_colors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """GLB only -- no feature_colors.json. POST /draft must still
    succeed for semantic regions but report featureIntentDraft.ok
    =false with the spec-worded skip message."""
    library = tmp_path / "lib"
    rev_dir = library / "parts" / PN / REV
    rev_dir.mkdir(parents=True)
    _sr_tests._write_synthetic_glb(rev_dir / f"{PN}_colored.glb",
                                   _sr_tests._aircraft_fixture())
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


def test_semantic_regions_draft_auto_writes_feature_intent_map(
    aircraft_library_no_regions: Path,
):
    """Spec: POST /api/part-semantic-regions/{pn}/draft writes BOTH
    {pn}_semantic_regions.json AND {pn}_feature_intent_map.json.
    Response surfaces featureIntentDraft.ok=true with the intent
    schema version + output path + feature count."""
    client = TestClient(server.app)
    r = client.post(f"/api/part-semantic-regions/{PN}/draft", json={"revision": "A"})
    assert r.status_code == 200, r.text
    body = r.json()
    # Semantic regions still land as before.
    assert body["ok"] is True
    assert body["partNumber"] == PN
    assert Path(body["outputPath"]).exists()

    # Auto-drafted intent map MUST be in the response + on disk.
    fid = body.get("featureIntentDraft")
    assert isinstance(fid, dict), body
    assert fid.get("ok") is True, fid
    assert fid.get("schemaVersion") == SCHEMA_VERSION
    assert fid.get("featureCount", 0) >= 1
    intent_path = Path(fid["outputPath"])
    assert intent_path.exists()
    assert intent_path.name == f"{PN}_feature_intent_map.json"
    # And the GET endpoint returns it without a second POST.
    g = client.get(f"/api/part-feature-intent/{PN}", params={"revision": "A"})
    assert g.status_code == 200, g.text
    # No warnings on the happy path.
    assert "warnings" not in body


def test_semantic_regions_draft_intent_map_carries_propeller_blade_thickness(
    aircraft_library_no_regions: Path,
):
    """End-to-end: the auto-drafted intent map should contain the
    same propeller-Boss-Extrude entry the standalone /draft path
    produces."""
    client = TestClient(server.app)
    r = client.post(f"/api/part-semantic-regions/{PN}/draft", json={"revision": "A"})
    assert r.status_code == 200, r.text
    g = client.get(f"/api/part-feature-intent/{PN}", params={"revision": "A"})
    doc = g.json()
    boss = next(e for e in doc["features"] if e["cadFeatureId"] == "ice_boss_extrude1")
    assert boss["editRole"] == "primary_edit_target"
    assert boss["controls"][0]["displayName"] == "blade thickness"


def test_semantic_regions_draft_soft_skips_intent_when_feature_colors_missing(
    aircraft_library_no_feature_colors: Path,
):
    """Spec: missing feature_colors.json must NOT fail the semantic
    regions draft. The response carries featureIntentDraft.ok=false
    with the spec-worded skip message + a warnings entry."""
    client = TestClient(server.app)
    r = client.post(f"/api/part-semantic-regions/{PN}/draft", json={"revision": "A"})
    assert r.status_code == 200, r.text
    body = r.json()
    # Semantic regions still succeeded.
    assert body["ok"] is True
    assert Path(body["outputPath"]).exists()

    # Intent map did NOT run, but reported the reason cleanly.
    fid = body.get("featureIntentDraft")
    assert isinstance(fid, dict)
    assert fid.get("ok") is False
    err = fid.get("error", "")
    assert "feature_colors.json" in err
    assert "skipped" in err.lower()
    # Warning surfaced at the top level too.
    warnings = body.get("warnings") or []
    assert any("feature_intent_draft_skipped" in w for w in warnings), warnings

    # And the intent map file does NOT exist on disk.
    intent_path = aircraft_library_no_feature_colors / "parts" / PN / REV / f"{PN}_feature_intent_map.json"
    assert not intent_path.exists()


def test_semantic_regions_draft_preserves_reviewed_intent_entry_on_auto_redraft(
    aircraft_library_no_regions: Path,
):
    """Spec: existing reviewed=true intent-map entry survives when
    the semantic-region draft triggers an intent re-draft.

    The flow:
      1. First semantic-regions /draft writes both sidecars.
      2. Operator curates the propeller Boss-Extrude entry in the
         intent map and marks it reviewed=true.
      3. Operator re-runs semantic-regions /draft (e.g. after fixing
         a region label). The auto-draft must NOT clobber the
         curated entry.
    """
    client = TestClient(server.app)
    # Step 1.
    r1 = client.post(f"/api/part-semantic-regions/{PN}/draft", json={"revision": "A"})
    assert r1.status_code == 200, r1.text

    # Step 2: curate the propeller boss entry.
    intent_doc = load_feature_intent_map(aircraft_library_no_regions, PN, REV)
    assert intent_doc is not None
    for e in intent_doc["features"]:
        if e["cadFeatureId"] == "ice_boss_extrude1":
            e["physicalName"] = "OPERATOR-LOCKED PROP BLADE"
            e["reviewed"]     = True
            e["controls"]     = [{
                "parameter":       "depth1_mm",
                "displayName":     "curated blade thickness",
                "units":           "mm",
                "physicalMeaning": "Locked by operator -- auto-redraft must not touch this.",
            }]
            break
    write_feature_intent_map(aircraft_library_no_regions, PN, REV, intent_doc)

    # Step 3: re-run semantic-regions /draft -> auto-draft fires.
    r2 = client.post(f"/api/part-semantic-regions/{PN}/draft", json={"revision": "A"})
    assert r2.status_code == 200, r2.text
    assert r2.json().get("featureIntentDraft", {}).get("ok") is True

    persisted = load_feature_intent_map(aircraft_library_no_regions, PN, REV)
    assert persisted is not None
    boss = next(e for e in persisted["features"] if e["cadFeatureId"] == "ice_boss_extrude1")
    assert boss["reviewed"]     is True
    assert boss["physicalName"] == "OPERATOR-LOCKED PROP BLADE"
    assert boss["controls"][0]["displayName"] == "curated blade thickness"
    # And the summary's curatedCount reflects the preserved entry.
    summary = persisted.get("summary") or {}
    assert summary.get("curatedCount", 0) >= 1


def test_semantic_regions_draft_response_field_present_even_when_intent_disabled(
    aircraft_library_no_feature_colors: Path,
):
    """Response contract guard: featureIntentDraft MUST be present
    in every 200 response so consumers can branch on
    `featureIntentDraft.ok` without optional-chain checks."""
    client = TestClient(server.app)
    r = client.post(f"/api/part-semantic-regions/{PN}/draft", json={"revision": "A"})
    assert r.status_code == 200
    assert "featureIntentDraft" in r.json()
