"""Tests for the Dimension Intent Map v0.1.

Covers:
- Path helper + load/write round trip
- POST /draft with no cadDimensions returns ok + warning + (possibly
  empty or drawing-seeded) mappings
- POST /draft with synthetic cadDimensions only -> CAD-only candidate
  mappings (low confidence, evidence='cad_only')
- POST /draft with synthetic drawing dim + matching cad dim ->
  high-confidence mapping (name_match evidence)
- reviewed=true mapping survives a re-draft (preservation contract,
  mirroring feature_intent + semantic_regions)
- Ambiguous same-value pairs do NOT produce a high-confidence exact
  mapping (matcher refuses to guess)
- GET absent returns 404 with the POST /draft hint
- PUT rejects duplicate mappingIds and missing required fields
- Semantic-regions /draft response carries dimensionIntentDraft
- Lookup helpers behave conservatively (None on tie / miss)
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
from ai_inspector.dimension_intent import (
    SCHEMA_VERSION,
    DIMENSION_INTENT_MAP_FILENAME,
    build_draft_dimension_intent_map,
    dimension_intent_map_path,
    load_dimension_intent_map,
    lookup_dimension_intent,
    lookup_dimension_intent_for_cad_dimension,
    write_dimension_intent_map,
)
from ai_inspector.dimension_intent.matcher import (
    canonical_dimension_type,
    find_drawing_match,
    VALUE_TOL_MM,
)
from ai_inspector.semantic_regions import (
    build_draft_regions,
    write_semantic_regions,
)

# Reuse the synthetic aircraft fixture used by feature_intent + sketch_intent
# so the dimension intent draft has real regions + feature_colors to chew on.
sys.path.insert(0, str(REPO_ROOT / "tests"))
import test_semantic_regions as _sr_tests  # noqa: E402


PN = "1030099"
REV = "revA"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def aircraft_library_with_regions(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Aircraft library with GLB + feature_colors + semantic_regions
    drafted, BUT no part.json cadDimensions and no drawing_map yet --
    the dimension intent draft must tolerate these missing inputs.
    Individual tests seed cadDimensions / drawing_map / descriptions
    as needed."""
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
    regions_doc = build_draft_regions(library, PN, REV)
    write_semantic_regions(library, PN, REV, regions_doc)
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


def _write_part_with_cad_dimensions(library: Path, dims: list) -> None:
    """Drop a minimal part.json into the rev dir carrying cadDimensions
    in the shape the extractor will eventually emit. Tests use this to
    exercise the primary CAD-side pass without waiting for extractor
    support."""
    rev_dir = library / "parts" / PN / REV
    doc = {
        "schemaVersion":  "test-fixture",
        "units":          "meters",
        "documentType":   "Part",
        "cadDimensions":  dims,
    }
    (rev_dir / "part.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_drawing_map(library: Path, view_name: str, dims: list) -> None:
    """Drop a {pn}_drawing_map.json at the library root with the
    annotation shape the matcher reads. dims is a list of
    (annotationName, featureName, value_meters, dim_type) tuples."""
    annotations = []
    for ann_name, feat_name, value_m, dim_type in dims:
        annotations.append({
            "annotationName": ann_name,
            "annotationType": "dimension",
            "featureName":    feat_name,
            "dimensionValue": value_m,
            "dimensionType":  dim_type,
            "isReference":    False,
            "matchKeys":      [ann_name, f"{ann_name}@{feat_name}"],
            "positionSheet":  [0.1, 0.1],
            "boundsSheet":    [],
            "anchorKind":     "annotationPosition",
            "leaders":        [],
            "isDangling":     False,
            "visible":        True,
            "noteText":       None,
            "dimensionText":  None,
            "textRuns":       [],
            "gtolText":       None,
        })
    doc = {
        "partNumber": PN,
        "sheets": [{
            "sheetName": "Sheet1",
            "scale":     [1, 1],
            "views": [{
                "viewName":     view_name,
                "viewType":     "named",
                "viewOutline":  [],
                "viewPosition": [0, 0],
                "viewScale":    [1, 1],
                "annotations":  annotations,
            }],
        }],
    }
    (library / f"{PN}_drawing_map.json").write_text(json.dumps(doc), encoding="utf-8")


def _write_descriptions(library: Path, mapping: dict) -> None:
    """Drop a {pn}_dimension_descriptions.json keyed by
    '{viewName}/{annotationName}'."""
    (library / f"{PN}_dimension_descriptions.json").write_text(json.dumps({
        "partNumber":   PN,
        "partName":     PN,
        "generatedBy":  "test",
        "descriptions": mapping,
    }), encoding="utf-8")


# ---------------------------------------------------------------------------
# Path + IO round trip
# ---------------------------------------------------------------------------

def test_path_helper_returns_canonical_layout(tmp_path: Path):
    p = dimension_intent_map_path(tmp_path, PN, REV)
    assert p == tmp_path / "parts" / PN / REV / DIMENSION_INTENT_MAP_FILENAME.format(pn=PN)


def test_load_missing_returns_none(tmp_path: Path):
    assert load_dimension_intent_map(tmp_path, PN, REV) is None


def test_write_then_read_round_trip(tmp_path: Path):
    sample = {
        "schemaVersion": SCHEMA_VERSION,
        "partNumber":    PN,
        "revision":      REV,
        "summary":       {"mappingCount": 0, "reviewedCount": 0,
                          "highConfidenceCount": 0, "candidateCount": 0},
        "mappings":      [],
    }
    out = write_dimension_intent_map(tmp_path, PN, REV, sample)
    assert out.exists()
    again = load_dimension_intent_map(tmp_path, PN, REV)
    assert again == sample


# ---------------------------------------------------------------------------
# Matcher unit tests (pure)
# ---------------------------------------------------------------------------

def test_canonical_dimension_type_maps_sw_api_names():
    assert canonical_dimension_type("swDiameterDimension") == "diameter"
    assert canonical_dimension_type("swRadialDimension")   == "radius"
    assert canonical_dimension_type("swAngularDimension")  == "angle"
    assert canonical_dimension_type("swVertLinearDimension") == "linear"
    assert canonical_dimension_type("swHorizLinearDimension") == "linear"
    assert canonical_dimension_type("")                    == "linear"
    assert canonical_dimension_type("unknown")             == "linear"


def test_matcher_exact_name_match_returns_high():
    """The drawing already names Sketch7+D1. Owner+short equal CAD owner
    +short -> high confidence regardless of value drift."""
    drawing = [
        {"annotationName": "D1", "ownerFeature": "Sketch7",
         "valueMm": 87.266, "dimensionType": "diameter",
         "drawingDimensionId": "Drawing View1/D1"},
    ]
    r = find_drawing_match(
        cad_full_name="D1@Sketch7", cad_owner="Sketch7", cad_short_name="D1",
        cad_value_mm=87.266, cad_dimension_type="diameter",
        region_label="Wheel / tire", drawing_dims=drawing, descriptions={},
    )
    assert r.matched is True
    assert r.confidence == "high"
    assert "name_match" in r.evidence
    assert "value_match" in r.evidence


def test_matcher_value_plus_region_is_high():
    """No name match but value agrees AND drawing description overlaps
    the CAD region label -> high confidence via value_match+region_match."""
    drawing = [
        {"annotationName": "D9", "ownerFeature": "SketchOther",
         "valueMm": 87.266, "dimensionType": "diameter",
         "drawingDimensionId": "Drawing View1/D9"},
    ]
    descriptions = {"Drawing View1/D9": "wheel outside diameter overall"}
    r = find_drawing_match(
        cad_full_name="D1@Sketch7", cad_owner="Sketch7", cad_short_name="D1",
        cad_value_mm=87.266, cad_dimension_type="diameter",
        region_label="Wheel tire assembly",
        drawing_dims=drawing, descriptions=descriptions,
    )
    assert r.matched is True
    assert r.confidence == "high"
    assert set(r.evidence) >= {"value_match", "region_match"}


def test_matcher_value_only_unique_is_low():
    """Single value hit with no region/description tie-breaker stays
    LOW so the curator can review it."""
    drawing = [
        {"annotationName": "D9", "ownerFeature": "SketchOther",
         "valueMm": 87.266, "dimensionType": "linear",
         "drawingDimensionId": "Drawing View1/D9"},
    ]
    r = find_drawing_match(
        cad_full_name="D1@Sketch7", cad_owner="Sketch7", cad_short_name="D1",
        cad_value_mm=87.266, cad_dimension_type="linear",
        region_label="", drawing_dims=drawing, descriptions={},
    )
    assert r.matched is True
    assert r.confidence == "low"
    assert r.evidence == ["value_match"]


def test_matcher_ambiguous_same_value_refuses_to_guess():
    """Two drawing dims at the same value, no region tie-breaker ->
    matched=False with evidence='ambiguous_value'. Prevents the silent
    wrong-pick that motivated the dimension intent map."""
    drawing = [
        {"annotationName": "D1", "ownerFeature": "SketchA",
         "valueMm": 87.266, "dimensionType": "linear",
         "drawingDimensionId": "Drawing View1/D1"},
        {"annotationName": "D2", "ownerFeature": "SketchB",
         "valueMm": 87.266, "dimensionType": "linear",
         "drawingDimensionId": "Drawing View2/D2"},
    ]
    r = find_drawing_match(
        cad_full_name="D3@SketchC", cad_owner="SketchC", cad_short_name="D3",
        cad_value_mm=87.266, cad_dimension_type="linear",
        region_label="", drawing_dims=drawing, descriptions={},
    )
    assert r.matched is False
    assert r.evidence == ["ambiguous_value"]


def test_matcher_value_tolerance_window():
    """Drift within VALUE_TOL_MM is accepted; outside is rejected."""
    drawing = [
        {"annotationName": "D9", "ownerFeature": "SketchX",
         "valueMm": 87.266 + VALUE_TOL_MM, "dimensionType": "linear",
         "drawingDimensionId": "Drawing View1/D9"},
    ]
    inside = find_drawing_match(
        cad_full_name="D1@Sketch7", cad_owner="Sketch7", cad_short_name="D1",
        cad_value_mm=87.266, cad_dimension_type="linear",
        region_label="", drawing_dims=drawing, descriptions={},
    )
    assert inside.matched is True
    # And outside the tolerance is rejected:
    drawing[0]["valueMm"] = 87.266 + (VALUE_TOL_MM * 5)
    outside = find_drawing_match(
        cad_full_name="D1@Sketch7", cad_owner="Sketch7", cad_short_name="D1",
        cad_value_mm=87.266, cad_dimension_type="linear",
        region_label="", drawing_dims=drawing, descriptions={},
    )
    assert outside.matched is False


# ---------------------------------------------------------------------------
# POST /draft via the HTTP endpoint
# ---------------------------------------------------------------------------

def test_post_draft_no_cad_dimensions_returns_ok_with_warning(
    aircraft_library_with_regions: Path,
):
    """The fixture has semantic_regions but no part.json cadDimensions
    and no drawing_map. POST /draft must still return ok=True with the
    cad_dimensions_missing warning + an empty (or sketch-seeded)
    mappings array. Never 404s on missing inputs."""
    client = TestClient(server.app)
    r = client.post(f"/api/part-dimension-intent/{PN}/draft", json={"revision": REV})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["schemaVersion"] == SCHEMA_VERSION
    assert body["mappingCount"] == 0
    warnings = body.get("warnings") or []
    assert any("cad_dimensions_missing" in w for w in warnings), warnings
    assert any("drawing_dimensions_missing" in w for w in warnings), warnings


def test_post_draft_cad_dimensions_only_produces_cad_only_candidates(
    aircraft_library_with_regions: Path,
):
    """Seed cadDimensions but NO drawing_map -> each CAD dim becomes a
    low-confidence cad_only mapping. Drawing-derived fields stay null."""
    _write_part_with_cad_dimensions(aircraft_library_with_regions, [
        {
            "dimensionFullName": "D1@Sketch7", "dimensionShortName": "D1",
            "ownerFeature": "Sketch7", "ownerType": "sketch",
            "controllingFeature": "Revolve2", "cadFeatureId": "revolution_revolve2",
            "valueMm": 87.266, "dimensionType": "diameter", "suppressed": False,
        },
    ])
    client = TestClient(server.app)
    r = client.post(f"/api/part-dimension-intent/{PN}/draft", json={"revision": REV})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["mappingCount"] >= 1
    doc = load_dimension_intent_map(aircraft_library_with_regions, PN, REV)
    cad_only = [m for m in doc["mappings"] if m["dimensionFullName"] == "D1@Sketch7"]
    assert len(cad_only) == 1
    m = cad_only[0]
    assert m["evidence"] == ["cad_only"]
    assert m["matchConfidence"] == "low"
    assert m["drawingDimensionId"] is None
    assert m["drawingValueMm"]    is None
    assert m["cadValueMm"]        == 87.266


def test_post_draft_matching_drawing_dim_creates_high_confidence_mapping(
    aircraft_library_with_regions: Path,
):
    """Seed both cadDimensions AND a drawing_map with the same sketch
    + short name + value. The matcher's exact-name path fires -> high
    confidence with name_match + value_match evidence. drawingDescription
    flows in from the dimension_descriptions sidecar."""
    _write_part_with_cad_dimensions(aircraft_library_with_regions, [
        {
            "dimensionFullName": "D1@Sketch7", "dimensionShortName": "D1",
            "ownerFeature": "Sketch7", "ownerType": "sketch",
            "controllingFeature": "Revolve2", "cadFeatureId": "revolution_revolve2",
            "valueMm": 87.266, "dimensionType": "diameter", "suppressed": False,
        },
    ])
    _write_drawing_map(aircraft_library_with_regions, "Drawing View1", [
        ("D1", "Sketch7", 0.087266, "swDiameterDimension"),
    ])
    _write_descriptions(aircraft_library_with_regions, {
        "Drawing View1/D1": "wheel outside diameter",
    })
    client = TestClient(server.app)
    r = client.post(f"/api/part-dimension-intent/{PN}/draft", json={"revision": REV})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["summary"]["highConfidenceCount"] >= 1

    doc = load_dimension_intent_map(aircraft_library_with_regions, PN, REV)
    hit = next(m for m in doc["mappings"] if m["dimensionFullName"] == "D1@Sketch7")
    assert hit["matchConfidence"] == "high"
    assert "name_match" in hit["evidence"]
    assert hit["drawingDimensionId"] == "Drawing View1/D1"
    assert abs(hit["drawingValueMm"] - 87.266) < 0.01
    assert hit["drawingDescription"] == "wheel outside diameter"
    assert hit["physicalName"] == "wheel outside diameter"


def test_post_draft_ambiguous_same_value_does_not_produce_high_confidence(
    aircraft_library_with_regions: Path,
):
    """Two drawing dims with the same value, one CAD dim with that
    value but a DIFFERENT (owner, short) name pair -> the matcher
    sees an ambiguous value match and refuses. The mapping lands as
    cad_only/low so the curator can resolve the ambiguity by hand."""
    _write_part_with_cad_dimensions(aircraft_library_with_regions, [
        {
            "dimensionFullName": "D1@SketchAlpha", "dimensionShortName": "D1",
            "ownerFeature": "SketchAlpha", "ownerType": "sketch",
            "controllingFeature": "Extrude1", "cadFeatureId": "ice_boss_extrude1",
            "valueMm": 87.266, "dimensionType": "linear", "suppressed": False,
        },
    ])
    _write_drawing_map(aircraft_library_with_regions, "Drawing View1", [
        ("D1", "SketchBeta",  0.087266, "swVertLinearDimension"),
        ("D2", "SketchGamma", 0.087266, "swVertLinearDimension"),
    ])
    client = TestClient(server.app)
    r = client.post(f"/api/part-dimension-intent/{PN}/draft", json={"revision": REV})
    assert r.status_code == 200, r.text
    doc = load_dimension_intent_map(aircraft_library_with_regions, PN, REV)
    hit = next(m for m in doc["mappings"] if m["dimensionFullName"] == "D1@SketchAlpha")
    assert hit["matchConfidence"] != "high", \
        f"ambiguous value pair must NOT yield high confidence; got {hit['matchConfidence']!r}"


# ---------------------------------------------------------------------------
# Reviewed-preservation contract
# ---------------------------------------------------------------------------

def test_reviewed_mapping_survives_redraft(aircraft_library_with_regions: Path):
    """Curator-edited mappings (reviewed=true) must carry over verbatim
    even when the heuristic builder would produce a different value /
    physical name for the same mappingId. Mirrors the feature_intent +
    semantic_regions preservation contract."""
    # First, do a clean draft so the file exists.
    _write_part_with_cad_dimensions(aircraft_library_with_regions, [
        {
            "dimensionFullName": "D1@Sketch7", "dimensionShortName": "D1",
            "ownerFeature": "Sketch7", "ownerType": "sketch",
            "controllingFeature": "Revolve2", "cadFeatureId": "revolution_revolve2",
            "valueMm": 87.266, "dimensionType": "diameter", "suppressed": False,
        },
    ])
    client = TestClient(server.app)
    assert client.post(f"/api/part-dimension-intent/{PN}/draft", json={"revision": REV}).status_code == 200

    # Operator edits the mapping in-place: rename physicalName + mark reviewed.
    doc = load_dimension_intent_map(aircraft_library_with_regions, PN, REV)
    mapping = next(m for m in doc["mappings"] if m["dimensionFullName"] == "D1@Sketch7")
    mapping_id = mapping["mappingId"]
    mapping["physicalName"] = "OPERATOR CURATED NAME"
    mapping["reviewed"]     = True
    write_dimension_intent_map(aircraft_library_with_regions, PN, REV, doc)

    # Re-draft -- the heuristic would normally rebuild physicalName
    # from the drawing description (or None), but the curated value
    # must survive verbatim.
    assert client.post(f"/api/part-dimension-intent/{PN}/draft", json={"revision": REV}).status_code == 200
    doc2 = load_dimension_intent_map(aircraft_library_with_regions, PN, REV)
    survivors = [m for m in doc2["mappings"] if m["mappingId"] == mapping_id]
    assert len(survivors) == 1, \
        f"re-draft produced {len(survivors)} mappings for {mapping_id!r}; expected 1"
    assert survivors[0]["physicalName"] == "OPERATOR CURATED NAME"
    assert survivors[0]["reviewed"]     is True


# ---------------------------------------------------------------------------
# GET / PUT endpoints
# ---------------------------------------------------------------------------

def test_get_absent_returns_404_with_post_hint(aircraft_library_with_regions: Path):
    client = TestClient(server.app)
    r = client.get(f"/api/part-dimension-intent/{PN}", params={"revision": "A"})
    assert r.status_code == 404, r.text
    detail = r.json()["detail"]
    assert "POST" in detail and "/draft" in detail, detail


def test_put_rejects_duplicate_mapping_ids(aircraft_library_with_regions: Path):
    client = TestClient(server.app)
    body = {
        "mappings": [
            {
                "mappingId": "dup:dup:D1@SketchA",
                "cadFeatureId": "f1", "ownerFeature": "SketchA",
                "dimensionShortName": "D1", "dimensionFullName": "D1@SketchA",
                "matchConfidence": "low",
            },
            {
                "mappingId": "dup:dup:D1@SketchA",
                "cadFeatureId": "f1", "ownerFeature": "SketchA",
                "dimensionShortName": "D1", "dimensionFullName": "D1@SketchA",
                "matchConfidence": "low",
            },
        ],
    }
    r = client.put(f"/api/part-dimension-intent/{PN}", params={"revision": "A"}, json=body)
    assert r.status_code == 400, r.text
    msg = json.dumps(r.json()["detail"])
    assert "duplicate mappingId" in msg, msg


def test_put_rejects_missing_required_fields(aircraft_library_with_regions: Path):
    client = TestClient(server.app)
    body = {
        "mappings": [
            {
                # mappingId + dimensionFullName + ownerFeature etc. omitted
                "matchConfidence": "low",
            },
        ],
    }
    r = client.put(f"/api/part-dimension-intent/{PN}", params={"revision": "A"}, json=body)
    assert r.status_code == 400, r.text
    msg = json.dumps(r.json()["detail"])
    assert "missing required string field" in msg, msg


def test_put_round_trips_valid_mapping(aircraft_library_with_regions: Path):
    client = TestClient(server.app)
    payload = {
        "mappings": [
            {
                "mappingId":           "wheel_tire:revolution_revolve2:D1@Sketch7",
                "physicalName":        "wheel outside diameter",
                "cadFeatureId":        "revolution_revolve2",
                "ownerFeature":        "Sketch7",
                "ownerType":           "sketch",
                "dimensionShortName":  "D1",
                "dimensionFullName":   "D1@Sketch7",
                "cadValueMm":          87.266,
                "matchConfidence":     "high",
                "reviewed":            True,
                "evidence":            ["operator_curated"],
            },
        ],
    }
    r = client.put(f"/api/part-dimension-intent/{PN}", params={"revision": "A"}, json=payload)
    assert r.status_code == 200, r.text
    saved = client.get(f"/api/part-dimension-intent/{PN}", params={"revision": "A"}).json()
    assert saved["mappings"][0]["physicalName"] == "wheel outside diameter"
    assert saved["summary"]["reviewedCount"] == 1
    assert saved["summary"]["highConfidenceCount"] == 1


# ---------------------------------------------------------------------------
# Auto-draft side effect on semantic-regions /draft
# ---------------------------------------------------------------------------

def test_semantic_regions_draft_response_carries_dimension_intent_draft(
    aircraft_library_with_regions: Path,
):
    """The existing semantic-regions /draft now ALSO drafts the
    dimension intent map (best-effort). The response must carry a
    dimensionIntentDraft block alongside the existing
    featureIntentDraft block so the curator UI can render both."""
    client = TestClient(server.app)
    r = client.post(f"/api/part-semantic-regions/{PN}/draft", json={"revision": REV})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "featureIntentDraft" in body
    assert "dimensionIntentDraft" in body
    di = body["dimensionIntentDraft"]
    assert di["ok"] is True
    assert di["schemaVersion"] == SCHEMA_VERSION
    assert "summary" in di
    # Warnings list is present even when empty; missing cadDimensions /
    # drawing map will populate it.
    assert isinstance(di.get("warnings"), list)


# ---------------------------------------------------------------------------
# Lookup helpers
# ---------------------------------------------------------------------------

def test_lookup_returns_unique_mapping_when_phrase_matches_physical_name(
    aircraft_library_with_regions: Path,
):
    """One phrase hit -> the helper returns that mapping. Reviewed flag
    tie-breaks among equal phrase scores."""
    write_dimension_intent_map(aircraft_library_with_regions, PN, REV, {
        "schemaVersion": SCHEMA_VERSION,
        "partNumber":    PN,
        "revision":      REV,
        "summary":       {"mappingCount": 1, "reviewedCount": 1,
                          "highConfidenceCount": 1, "candidateCount": 0},
        "mappings": [
            {
                "mappingId":          "wheel_tire:rev2:D1@Sketch7",
                "physicalName":       "wheel outside diameter",
                "semanticRegionId":   "wheel_tire",
                "cadFeatureId":       "revolution_revolve2",
                "ownerFeature":       "Sketch7",
                "ownerType":          "sketch",
                "dimensionShortName": "D1",
                "dimensionFullName":  "D1@Sketch7",
                "matchConfidence":    "high",
                "reviewed":           True,
            },
        ],
    })
    hit = lookup_dimension_intent(
        aircraft_library_with_regions, PN, REV,
        "set the wheel outside diameter to 90 mm",
    )
    assert hit is not None
    assert hit["dimensionFullName"] == "D1@Sketch7"


def test_lookup_returns_none_on_tie(aircraft_library_with_regions: Path):
    """Two mappings with the same phrase signal + same confidence ->
    tie -> None. Caller (Sage handoff) must then default to operator
    selection."""
    write_dimension_intent_map(aircraft_library_with_regions, PN, REV, {
        "schemaVersion": SCHEMA_VERSION,
        "partNumber":    PN, "revision": REV,
        "summary":       {"mappingCount": 2, "reviewedCount": 0,
                          "highConfidenceCount": 0, "candidateCount": 2},
        "mappings": [
            {
                "mappingId":          "wheel_tire:rev2:D1@Sketch7",
                "physicalName":       "wheel diameter",
                "cadFeatureId":       "revolution_revolve2",
                "ownerFeature":       "Sketch7",
                "dimensionShortName": "D1",
                "dimensionFullName":  "D1@Sketch7",
                "matchConfidence":    "medium",
            },
            {
                "mappingId":          "wheel_tire:rev3:D2@Sketch8",
                "physicalName":       "wheel diameter",
                "cadFeatureId":       "revolution_revolve3",
                "ownerFeature":       "Sketch8",
                "dimensionShortName": "D2",
                "dimensionFullName":  "D2@Sketch8",
                "matchConfidence":    "medium",
            },
        ],
    })
    hit = lookup_dimension_intent(
        aircraft_library_with_regions, PN, REV, "the wheel diameter",
    )
    assert hit is None


def test_lookup_by_full_name_returns_exact_entry(aircraft_library_with_regions: Path):
    write_dimension_intent_map(aircraft_library_with_regions, PN, REV, {
        "schemaVersion": SCHEMA_VERSION,
        "partNumber":    PN, "revision": REV,
        "summary":       {"mappingCount": 1, "reviewedCount": 0,
                          "highConfidenceCount": 1, "candidateCount": 0},
        "mappings": [
            {
                "mappingId":          "wheel_tire:rev2:D1@Sketch7",
                "physicalName":       "wheel outside diameter",
                "cadFeatureId":       "revolution_revolve2",
                "ownerFeature":       "Sketch7",
                "dimensionShortName": "D1",
                "dimensionFullName":  "D1@Sketch7",
                "matchConfidence":    "high",
            },
        ],
    })
    hit = lookup_dimension_intent_for_cad_dimension(
        aircraft_library_with_regions, PN, REV, "D1@Sketch7",
    )
    assert hit is not None
    assert hit["physicalName"] == "wheel outside diameter"
    miss = lookup_dimension_intent_for_cad_dimension(
        aircraft_library_with_regions, PN, REV, "D2@Sketch99",
    )
    assert miss is None
