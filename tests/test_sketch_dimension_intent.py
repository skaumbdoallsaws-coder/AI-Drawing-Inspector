"""Tests for curated sketch-dimension naming.

This layer maps operator-reviewed physical names like "front strut
diameter" to sketch-owned SolidWorks dimensions like D1@Sketch270.
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
from ai_inspector.feature_intent import write_feature_intent_map
from ai_inspector.semantic_regions import semantic_regions_path
from ai_inspector.sketch_intent import (
    SCHEMA_VERSION,
    list_sketch_dimension_intents,
    load_sketch_dimension_intent_map,
    lookup_sketch_dimension_intent,
    sketch_dimension_intent_map_path,
    write_sketch_dimension_intent_map,
)


PN = "1030999"
REV = "revA"
CAD_ID = "ice_boss_extrude2"


@pytest.fixture
def sketch_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    library = tmp_path / "lib"
    rev_dir = library / "parts" / PN / REV
    rev_dir.mkdir(parents=True)

    semantic_regions_path(library, PN, REV).write_text(json.dumps({
        "schemaVersion": "semantic-regions-1.3.0",
        "partNumber": PN,
        "revision": REV,
        "regions": [
            {
                "regionId": "strut_outer",
                "label": "Outer wing strut",
                "aliases": ["outer strut", "outer wing strut"],
                "confidence": "high",
                "reviewed": False,
                "glbNodes": [CAD_ID],
                "visualTargets": {"glbNodes": [CAD_ID]},
                "sourceFeatures": ["Boss-Extrude2"],
                "cadTargets": {
                    "cadFeatureIds": [CAD_ID],
                    "sourceFeatures": ["Boss-Extrude2"],
                },
                "placementCapabilities": ["reference_only"],
                "placementSurfaces": [],
                "editReadiness": "not_ready",
            },
        ],
    }), encoding="utf-8")

    write_feature_intent_map(library, PN, REV, {
        "schemaVersion": "feature-intent-map-1.0.0",
        "partNumber": PN,
        "revision": REV,
        "summary": {},
        "features": [
            {
                "cadFeatureId": CAD_ID,
                "solidWorksName": "Boss-Extrude2",
                "regionId": "strut_outer",
                "regionLabel": "Outer wing strut",
                "physicalName": "outer wing strut body",
                "featureRole": "creates the strut body",
                "editRole": "primary_edit_target",
                "controls": [],
                "downstreamFeatures": ["mirrorsolid_mirror4"],
                "reviewed": True,
                "confidence": "operator_confirmed",
            },
        ],
    })

    write_sketch_dimension_intent_map(library, PN, REV, {
        "schemaVersion": SCHEMA_VERSION,
        "partNumber": PN,
        "revision": REV,
        "summary": {"dimensionCount": 2, "reviewedCount": 2},
        "dimensions": [
            {
                "cadFeatureId": CAD_ID,
                "solidWorksName": "Boss-Extrude2",
                "regionId": "strut_outer",
                "regionLabel": "Outer wing strut",
                "sketchFeature": "Sketch270",
                "dimensionShortName": "D1",
                "dimensionFullName": "D1@Sketch270",
                "displayName": "front strut diameter",
                "aliases": ["front strut dia"],
                "controlType": "diameter",
                "physicalMeaning": "Changing this adjusts the front outer wing strut diameter.",
                "units": "mm",
                "reviewed": True,
                "confidence": "operator_confirmed",
            },
            {
                "cadFeatureId": CAD_ID,
                "solidWorksName": "Boss-Extrude2",
                "regionId": "strut_outer",
                "regionLabel": "Outer wing strut",
                "sketchFeature": "Sketch270",
                "dimensionShortName": "D2",
                "dimensionFullName": "D2@Sketch270",
                "displayName": "rear strut diameter",
                "aliases": ["rear strut dia"],
                "controlType": "diameter",
                "physicalMeaning": "Changing this adjusts the rear outer wing strut diameter.",
                "units": "mm",
                "reviewed": True,
                "confidence": "operator_confirmed",
            },
        ],
    })

    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


def test_lookup_sketch_dimension_intent_matches_reviewed_physical_name(sketch_library: Path):
    hit = lookup_sketch_dimension_intent(
        sketch_library,
        PN,
        REV,
        CAD_ID,
        "set the front strut diameter to 3 mm",
        "diameter",
    )
    assert hit is not None
    assert hit["sketchFeature"] == "Sketch270"
    assert hit["dimensionShortName"] == "D1"
    assert hit["displayName"] == "front strut diameter"


def test_lookup_sketch_dimension_intent_refuses_ambiguous_axis_only(sketch_library: Path):
    hit = lookup_sketch_dimension_intent(
        sketch_library,
        PN,
        REV,
        CAD_ID,
        "set the diameter to 3 mm",
        "diameter",
    )
    assert hit is None


def test_list_sketch_dimension_intents_returns_options_for_cad_feature(sketch_library: Path):
    options = list_sketch_dimension_intents(sketch_library, PN, REV, CAD_ID)
    assert [o["dimensionShortName"] for o in options] == ["D1", "D2"]


def test_http_put_get_sketch_dimension_intent_map(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    library = tmp_path / "lib"
    (library / "parts" / PN / REV).mkdir(parents=True)
    monkeypatch.setattr(server, "LIBRARY_DIR", library)

    client = TestClient(server.app)
    body = {
        "dimensions": [
            {
                "cadFeatureId": CAD_ID,
                "sketchFeature": "Sketch270",
                "dimensionShortName": "D1",
                "displayName": "front strut diameter",
                "controlType": "diameter",
                "reviewed": True,
            }
        ]
    }
    r = client.put(f"/api/part-sketch-dimension-intent/{PN}", params={"revision": "A"}, json=body)
    assert r.status_code == 200, r.text
    assert r.json()["schemaVersion"] == SCHEMA_VERSION
    assert r.json()["summary"]["dimensionCount"] == 1

    persisted = load_sketch_dimension_intent_map(library, PN, REV)
    assert persisted is not None
    assert persisted["dimensions"][0]["displayName"] == "front strut diameter"
    assert sketch_dimension_intent_map_path(library, PN, REV).exists()

    g = client.get(f"/api/part-sketch-dimension-intent/{PN}", params={"revision": "A"})
    assert g.status_code == 200, g.text
    assert g.json()["dimensions"][0]["dimensionShortName"] == "D1"


def test_cad_edit_handoff_named_sketch_dimension_promotes_and_prefills_target(sketch_library: Path):
    payload = server._semantic_region_cad_edit_handoff_payload(
        sketch_library,
        PN,
        REV,
        "outer wing strut",
        "set the front strut diameter to 3 mm",
    )
    assert payload is not None
    assert payload["intent"]["action"] == "sketch_dimension_change"
    assert payload["intent"]["source"] == "parser+sketch_intent_map"
    assert payload["target"]["sketchFeature"] == "Sketch270"
    assert payload["target"]["dimensionShortName"] == "D1"
    assert payload["target"]["sketchDimensionIntent"]["displayName"] == "front strut diameter"
    assert payload["target"]["downstreamFeatures"][0]["cadFeatureId"] == "mirrorsolid_mirror4"


def test_cad_edit_handoff_generic_sketch_request_keeps_operator_selector(sketch_library: Path):
    payload = server._semantic_region_cad_edit_handoff_payload(
        sketch_library,
        PN,
        REV,
        "outer wing strut",
        "edit the sketch dimension controlling the outer wing strut thickness to 3 mm",
    )
    assert payload is not None
    assert payload["intent"]["action"] == "sketch_dimension_change"
    assert payload["target"]["sketchFeature"] is None
    assert payload["target"]["dimensionShortName"] is None
    assert [o["displayName"] for o in payload["target"]["sketchDimensionOptions"]] == [
        "front strut diameter",
        "rear strut diameter",
    ]
