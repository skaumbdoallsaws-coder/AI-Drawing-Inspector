"""Tests for the Part Semantic Region Builder MVP.

Covers:
  - glb_inspect: bbox extraction, double-sided detection, error paths
  - rules: axis-frame detection, individual classifier rules
  - builder: end-to-end synthetic aircraft, preservation of reviewed=true,
             pure-solid part (no aircraft rules fire)
  - HTTP: GET 404 when absent, POST creates the file and is idempotent
          (re-post still works after a reviewed region is locked)
  - live sanity check: if 400S_Sorted_Library/parts/1030034/revB exists,
    the real GLB must produce the expected aircraft regions
"""

from __future__ import annotations

import json
import os
import struct
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
    EDIT_READINESS_VALUES,
    PLACEMENT_CAPABILITIES,
    PLACEMENT_SURFACE_ROLES,
    PLACEMENT_SURFACE_TYPES,
    SCHEMA_VERSION,
    build_draft_regions,
    semantic_regions_path,
    write_semantic_regions,
)
from ai_inspector.semantic_regions.glb_inspect import inspect_glb
from ai_inspector.semantic_regions.rules import (
    LABELS,
    classify_node_aircraft,
    detect_axis_frame,
    fallback_bucket_id,
)


# ---------------------------------------------------------------------------
# Synthetic GLB writer -- the real SolidWorksExtractor output is huge;
# we write a tiny one whose ONLY purpose is to exercise the JSON chunk
# parser + the per-mesh bbox / doubleSided fields. The BIN chunk is
# legal-empty (zero-length data with the right header).
# ---------------------------------------------------------------------------

_GLB_MAGIC      = 0x46546C67
_JSON_CHUNK     = 0x4E4F534A
_BIN_CHUNK      = 0x004E4942


def _write_synthetic_glb(
    out_path: Path,
    meshes: List[Tuple[str, Tuple[float, float, float], Tuple[float, float, float], bool]],
    generator: str = "test-fixture",
) -> None:
    """Write a glb that has the minimum structure needed for
    inspect_glb to extract per-mesh name + bbox + doubleSided.

    Each input tuple: (mesh_name, bbox_min, bbox_max, double_sided)."""
    accessors = []
    materials = []
    meshes_doc = []
    for i, (name, mn, mx, ds) in enumerate(meshes):
        # POSITION accessor: bufferView is irrelevant for our parser,
        # but min/max are exactly what inspect_glb reads.
        accessors.append({
            "bufferView":    0,
            "componentType": 5126,
            "count":         3,
            "type":          "VEC3",
            "min":           list(mn),
            "max":           list(mx),
        })
        material = {"name": name, "pbrMetallicRoughness": {"baseColorFactor": [0.5, 0.5, 0.5, 1.0]}}
        if ds:
            material["doubleSided"] = True
        materials.append(material)
        meshes_doc.append({
            "name": name,
            "primitives": [{
                "attributes": {"POSITION": i},
                "material":   i,
            }],
        })

    gltf = {
        "asset":     {"version": "2.0", "generator": generator},
        "scenes":    [{"nodes": list(range(len(meshes)))}],
        "scene":     0,
        "nodes":     [{"mesh": i, "name": meshes[i][0]} for i in range(len(meshes))],
        "meshes":    meshes_doc,
        "materials": materials,
        "accessors": accessors,
        "bufferViews": [{"buffer": 0, "byteOffset": 0, "byteLength": 0}],
        "buffers":   [{"byteLength": 0}],
    }
    json_bytes = json.dumps(gltf).encode("ascii")
    # Pad JSON chunk to 4-byte alignment with spaces
    pad = (4 - len(json_bytes) % 4) % 4
    json_chunk = json_bytes + (b" " * pad)
    bin_chunk = b""
    total = 12 + 8 + len(json_chunk) + 8 + len(bin_chunk)
    with out_path.open("wb") as f:
        f.write(struct.pack("<III", _GLB_MAGIC, 2, total))
        f.write(struct.pack("<II", len(json_chunk), _JSON_CHUNK))
        f.write(json_chunk)
        f.write(struct.pack("<II", len(bin_chunk), _BIN_CHUNK))


def _aircraft_fixture() -> List[Tuple[str, Tuple[float, float, float], Tuple[float, float, float], bool]]:
    """Synthetic mini-aircraft. Z = length (nose at +20, tail at -500),
    Y = vertical, X = lateral. Bboxes copied from the real 1030034 revB
    structure so the rules exercise the same regime they would in
    production -- just with three nodes per region instead of dozens."""
    return [
        # Propeller cluster (small XY, near front of Z range)
        ("revolution_revolve1",           (-6.0, -6.0,   0.0), (  6.0,   6.0,  19.0), False),
        ("ice_boss_extrude1",             ( 2.9,  0.8,   8.0), ( 55.5,  36.1,   8.5), False),
        ("cirpattern1",                   (-55.5, -63.7, 8.0), ( 12.6,  36.2,   8.5), False),
        # Top wing (high Y, wide X)
        ("planarsurface_top_wing",        (-252.5, 82.1, -192.4), (252.5, 87.1, -87.4), True),
        ("extrurefsurface_top_wing_root", (-35.0,  82.1, -192.4), ( 35.0, 87.1, -155.0), True),
        # Lower wing (low Y, wide X)
        ("extrurefsurface_lower_wing",    (-200.0, -37.1, -192.4), (200.0, -32.1, -87.4), True),
        ("revolvrefsurf_lower_wingtip_p", (147.5, -37.1, -192.4),  (252.5, -32.1, -87.4), True),
        # Outer strut +X (narrow X at large +X, tall Y)
        ("ice_boss_extrude_strut_outer_p", (197.5, -32.1, -172.4), (202.5, 82.1, -107.4), False),
        # Tail horizontal stabilizer (back Z, low Y, wider X)
        ("netblend_horiz_stab_p",         (4.8,   7.0,  -475.7), ( 75.0, 18.8, -387.5), True),
        ("netblend_horiz_stab_pm",        (75.0,  12.9, -460.9), (148.6, 16.4, -399.7), True),
        # Tail vertical stabilizer (back Z, high Y, narrow X near center)
        ("netblend_vert_stab",            (0.0,   22.2, -492.9), (  6.2, 73.0, -408.3), True),
        # Tail end cap (very back Z)
        ("planarsurface_tail_end",        (-2.5,  6.8,  -500.0), (  2.5, 19.7, -500.0), True),
        # Construction feature spanning whole length -> fuselage_candidate
        ("pline_split_line1",             (-26.9, -36.7, -500.0), ( 27.1, 36.0, -15.0), True),
    ]


def _solid_only_fixture() -> List[Tuple[str, Tuple[float, float, float], Tuple[float, float, float], bool]]:
    """Compact solid piston-like part: all solids, no surface meshes,
    no aircraft-style rules should fire (everything ends up in name
    fallback buckets)."""
    return [
        ("revolution_revolve1", (-30.0, -30.0,   0.0), (30.0, 30.0,  60.0), False),
        ("dome1",               (-30.0, -30.0,  60.0), (30.0, 30.0,  65.0), False),
        ("ice_cut_extrude1",    (-12.0, -12.0,  10.0), (12.0, 12.0,  55.0), False),
        ("ice_cut_extrude2",    (-12.0, -12.0,  10.0), (12.0, 12.0,  55.0), False),
        ("ice_boss_extrude1",   (-22.0, -22.0,   5.0), (22.0, 22.0,  10.0), False),
        ("mirrorpattern_mirror1", (-22.0, -22.0,  5.0), (22.0, 22.0,  10.0), False),
    ]


# ---------------------------------------------------------------------------
# Fixture: lib_under_part dir with the synthetic GLB written into the
# canonical parts/{pn}/{rev}/{pn}_colored.glb path
# ---------------------------------------------------------------------------

@pytest.fixture
def aircraft_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    library = tmp_path / "lib"
    pn, rev = "1030099", "revA"
    rev_dir = library / "parts" / pn / rev
    rev_dir.mkdir(parents=True)
    _write_synthetic_glb(rev_dir / f"{pn}_colored.glb", _aircraft_fixture())
    # Minimal feature_colors.json so sourceFeatures populates
    (rev_dir / f"{pn}_feature_colors.json").write_text(json.dumps({
        "partNumber": pn,
        "features": [
            {"cadFeatureId": n, "swName": n.replace("_", " ").title()}
            for n, *_ in _aircraft_fixture()
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


@pytest.fixture
def solid_only_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    library = tmp_path / "lib"
    pn, rev = "1020099", "revA"
    rev_dir = library / "parts" / pn / rev
    rev_dir.mkdir(parents=True)
    _write_synthetic_glb(rev_dir / f"{pn}_colored.glb", _solid_only_fixture())
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    yield library


# ---------------------------------------------------------------------------
# glb_inspect
# ---------------------------------------------------------------------------

def test_glb_inspect_extracts_bboxes_and_doubleSided(aircraft_library: Path):
    glb = aircraft_library / "parts" / "1030099" / "revA" / "1030099_colored.glb"
    summary = inspect_glb(glb)
    assert summary.generator == "test-fixture"
    assert len(summary.nodes) == len(_aircraft_fixture())
    # Spot-check: top-wing bbox
    by_name = {n.name: n for n in summary.nodes}
    top = by_name["planarsurface_top_wing"]
    assert top.bbox_min == (-252.5, 82.1, -192.4)
    assert top.bbox_max == (252.5, 87.1, -87.4)
    assert top.double_sided is True
    # Overall bbox is union
    assert summary.overall_min[0] == pytest.approx(-252.5)
    assert summary.overall_max[2] == pytest.approx(19.0)


def test_glb_inspect_missing_file_raises():
    with pytest.raises(FileNotFoundError):
        inspect_glb(Path("does-not-exist.glb"))


def test_glb_inspect_bad_magic_raises(tmp_path: Path):
    p = tmp_path / "bad.glb"
    p.write_bytes(b"NOPE" + b"\x00" * 100)
    with pytest.raises(ValueError, match="Not a GLB"):
        inspect_glb(p)


# ---------------------------------------------------------------------------
# Rules
# ---------------------------------------------------------------------------

def test_detect_axis_frame_picks_longest_as_length(aircraft_library: Path):
    glb = aircraft_library / "parts" / "1030099" / "revA" / "1030099_colored.glb"
    summary = inspect_glb(glb)
    frame = detect_axis_frame(summary)
    # Synthetic part: Z spans -500..+19 (519 units), X spans -252..+252
    # (505 units), Y spans -64..+87 (~151 units). Length=Z, lateral=X,
    # vertical=Y.
    assert frame.length_axis == 2,   f"expected Z=length, got axis {frame.length_axis}"
    assert frame.lateral_axis == 0,  f"expected X=lateral, got axis {frame.lateral_axis}"
    assert frame.vertical_axis == 1, f"expected Y=vertical, got axis {frame.vertical_axis}"


def test_classify_propeller(aircraft_library: Path):
    glb = aircraft_library / "parts" / "1030099" / "revA" / "1030099_colored.glb"
    summary = inspect_glb(glb)
    frame = detect_axis_frame(summary)
    revolve = next(n for n in summary.nodes if n.name == "revolution_revolve1")
    verdict = classify_node_aircraft(revolve, frame)
    assert verdict is not None
    region_id, confidence = verdict
    assert region_id == "propeller"
    assert confidence == "high"


def test_classify_top_and_lower_wings(aircraft_library: Path):
    glb = aircraft_library / "parts" / "1030099" / "revA" / "1030099_colored.glb"
    summary = inspect_glb(glb)
    frame = detect_axis_frame(summary)
    by_name = {n.name: n for n in summary.nodes}
    top    = classify_node_aircraft(by_name["planarsurface_top_wing"], frame)
    lower  = classify_node_aircraft(by_name["extrurefsurface_lower_wing"], frame)
    assert top   == ("top_wing", "high")
    assert lower == ("lower_wing", "high")


def test_classify_tail_horizontal_and_vertical(aircraft_library: Path):
    glb = aircraft_library / "parts" / "1030099" / "revA" / "1030099_colored.glb"
    summary = inspect_glb(glb)
    frame = detect_axis_frame(summary)
    by_name = {n.name: n for n in summary.nodes}
    horiz = classify_node_aircraft(by_name["netblend_horiz_stab_p"], frame)
    vert  = classify_node_aircraft(by_name["netblend_vert_stab"], frame)
    assert horiz is not None and horiz[0] == "tail_horizontal_stabilizer"
    assert vert  is not None and vert[0]  == "tail_vertical_stabilizer"


def test_classify_fuselage_candidate_for_split_line(aircraft_library: Path):
    glb = aircraft_library / "parts" / "1030099" / "revA" / "1030099_colored.glb"
    summary = inspect_glb(glb)
    frame = detect_axis_frame(summary)
    by_name = {n.name: n for n in summary.nodes}
    split = classify_node_aircraft(by_name["pline_split_line1"], frame)
    assert split == ("fuselage_candidate", "low"), \
        "split-line construction feature must route to fuselage_candidate (low)"


def test_fallback_bucket_id_groups_by_feature_type():
    # Always bucket by the SolidWorks type-name token (leading
    # lowercase run), not the full slugified feature name.
    assert fallback_bucket_id("netblend_boundary_surface3") == "features_netblend"
    assert fallback_bucket_id("ice_boss_extrude2")          == "features_ice"
    assert fallback_bucket_id("revolution_revolve1")        == "features_revolution"
    assert fallback_bucket_id("mirrorsolid_mirror4")        == "features_mirrorsolid"
    # Single-token names with trailing digits collapse to the token.
    assert fallback_bucket_id("dome1")                       == "features_dome"
    assert fallback_bucket_id("sweep1")                      == "features_sweep"


# ---------------------------------------------------------------------------
# Builder end-to-end
# ---------------------------------------------------------------------------

def test_build_draft_regions_aircraft_assigns_every_node(aircraft_library: Path):
    pn, rev = "1030099", "revA"
    doc = build_draft_regions(aircraft_library, pn, rev)
    assert doc["schemaVersion"] == SCHEMA_VERSION
    assert doc["partNumber"]    == pn
    assert doc["revision"]      == rev
    # Required block keys
    assert "axisFrame" in doc
    assert "summary"   in doc
    assert "regions"   in doc
    # Every node appears in EXACTLY one region (no doubles, no drops).
    all_node_names = {n[0] for n in _aircraft_fixture()}
    assigned: List[str] = []
    for r in doc["regions"]:
        assigned.extend(r["glbNodes"])
    assert sorted(assigned) == sorted(all_node_names), \
        f"node assignment mismatch: expected {sorted(all_node_names)}, got {sorted(assigned)}"
    assert len(assigned) == len(set(assigned)), \
        "no node should appear in more than one region"
    # Region IDs we expect for the aircraft fixture
    region_ids = {r["regionId"] for r in doc["regions"]}
    expected_subset = {
        "propeller", "top_wing", "lower_wing",
        "tail_horizontal_stabilizer", "tail_vertical_stabilizer",
        "fuselage_candidate",
    }
    missing = expected_subset - region_ids
    assert not missing, f"missing expected regions: {missing}"
    # Every region carries the required keys -- the original 1.0.0
    # contract, the 1.1.0 CAD-edit orchestration scaffolding, and
    # the 1.2.0 CAD-edit planning placeholders.
    for r in doc["regions"]:
        for k in ("regionId", "label", "aliases", "glbNodes",
                  "sourceFeatures", "confidence", "reviewed", "notes",
                  # 1.1.0 forward-compat fields
                  "requiresReview", "editReadiness",
                  "visualTargets", "cadTargets", "editableParameters",
                  # 1.2.0 placement scaffolding
                  "placementSurfaces", "placementCapabilities"):
            assert k in r, f"region {r.get('regionId')!r} missing {k}"
        assert r["reviewed"] is False, "new drafts must always start unreviewed"
        assert r["confidence"] in ("low", "medium", "high")


def test_build_draft_regions_sourceFeatures_populated_from_feature_colors(aircraft_library: Path):
    doc = build_draft_regions(aircraft_library, "1030099", "revA")
    propeller = next(r for r in doc["regions"] if r["regionId"] == "propeller")
    # feature_colors fixture mapped cadFeatureId -> Title Case version
    assert any("Revolve1" in s for s in propeller["sourceFeatures"])


def test_build_draft_regions_schema_1_1_0_cad_orchestration_fields(aircraft_library: Path):
    """Schema 1.1.0 adds visualTargets / cadTargets / editableParameters /
    editReadiness / requiresReview so the doc is wire-ready for future
    SOLIDWORKS Sage CAD-edit orchestration. The MVP populates
    visualTargets.glbNodes and cadTargets.sourceFeatures from what
    we know today; everything else is intentionally empty and the
    region is flagged not_ready until the dependency extractor lands."""
    doc = build_draft_regions(aircraft_library, "1030099", "revA")
    # The 1.1.0 contract is the FLOOR -- later schema bumps must keep
    # these fields present. We assert against the exported constant
    # (not a string literal) so a bump to 1.3.0 / 2.0.0 doesn't have
    # to touch this test as long as the orchestration fields stay.
    assert doc["schemaVersion"] == SCHEMA_VERSION
    for r in doc["regions"]:
        # Top-level orchestration flags
        assert r["requiresReview"] is True, \
            f"{r['regionId']} must require review while not_ready"
        assert r["editReadiness"] == "not_ready", \
            f"{r['regionId']} editReadiness must be not_ready until extractor exists; got {r['editReadiness']!r}"
        assert r["editReadiness"] in EDIT_READINESS_VALUES
        # visualTargets mirrors glbNodes byte-for-byte
        assert isinstance(r["visualTargets"], dict)
        assert r["visualTargets"]["glbNodes"] == r["glbNodes"]
        # cadTargets carries all five expected keys, sourceFeatures
        # mirrors the top-level field, the remaining four are empty
        ct = r["cadTargets"]
        assert isinstance(ct, dict)
        for key in ("sourceFeatures", "upstreamFeatures", "sketches", "planes", "dimensions"):
            assert key in ct, f"{r['regionId']} cadTargets missing {key}"
            assert isinstance(ct[key], list)
        assert ct["sourceFeatures"]   == r["sourceFeatures"]
        assert ct["upstreamFeatures"] == []
        assert ct["sketches"]         == []
        assert ct["planes"]           == []
        assert ct["dimensions"]       == []
        # editableParameters seeded empty
        assert r["editableParameters"] == []


def test_build_draft_regions_upgrades_legacy_reviewed_region_to_1_1_0(aircraft_library: Path):
    """A reviewed region carried over from a pre-1.1.0 file lacks
    visualTargets / cadTargets / editableParameters / editReadiness /
    requiresReview. The builder must add those fields in place WITHOUT
    overwriting any curator content -- editReadiness is upgraded only
    if absent, so a curator who set editReadiness='ready' on a region
    keeps that value across re-draft."""
    pn, rev = "1030099", "revA"
    # First write a synthetic 1.0.0-shaped file: reviewed region has
    # only the original-spec fields, no visualTargets / cadTargets.
    out = semantic_regions_path(aircraft_library, pn, rev)
    out.parent.mkdir(parents=True, exist_ok=True)
    legacy_doc = {
        "schemaVersion": "part-semantic-regions-1.0.0",
        "partNumber":    pn,
        "revision":      rev,
        "regions": [
            {
                "regionId":      "propeller",
                "label":         "Curated spinner + 2-blade prop",
                "aliases":       ["spinner"],
                "glbNodes":      ["revolution_revolve1",
                                  "ice_boss_extrude1",
                                  "cirpattern1"],
                "sourceFeatures": ["Revolve1", "Boss-Extrude1", "CirPattern1"],
                "confidence":    "high",
                "reviewed":      True,
                "notes":         "Operator-curated 2026-05-21 under schema 1.0.0.",
            },
        ],
    }
    out.write_text(json.dumps(legacy_doc), encoding="utf-8")

    # Re-draft -- the legacy reviewed region must upgrade in place.
    doc = build_draft_regions(aircraft_library, pn, rev)
    propellers = [r for r in doc["regions"] if r["regionId"] == "propeller"]
    assert len(propellers) == 1
    p = propellers[0]
    # Curator content preserved verbatim
    assert p["reviewed"]   is True
    assert p["label"]      == "Curated spinner + 2-blade prop"
    assert p["notes"]      == "Operator-curated 2026-05-21 under schema 1.0.0."
    assert p["aliases"]    == ["spinner"]
    # New 1.1.0 fields seeded
    assert p["requiresReview"] is True
    assert p["editReadiness"]  == "not_ready"
    assert p["visualTargets"]["glbNodes"] == p["glbNodes"]
    assert p["cadTargets"]["sourceFeatures"] == p["sourceFeatures"]
    for key in ("upstreamFeatures", "sketches", "planes", "dimensions"):
        assert p["cadTargets"][key] == []
    assert p["editableParameters"] == []


def test_upgrade_preserves_curator_set_editReadiness(aircraft_library: Path):
    """When a curator has already flipped editReadiness='ready' on a
    reviewed region (mid-1.1.0 lifecycle), the next re-draft must NOT
    revert it to 'not_ready'. Seeded-only semantics; setdefault means
    populated values pass through untouched."""
    pn, rev = "1030099", "revA"
    out = semantic_regions_path(aircraft_library, pn, rev)
    out.parent.mkdir(parents=True, exist_ok=True)
    seed = {
        "schemaVersion": "part-semantic-regions-1.1.0",
        "partNumber":    pn,
        "revision":      rev,
        "regions": [{
            "regionId":      "propeller",
            "label":         "Spinner (operator-locked)",
            "aliases":       [],
            "glbNodes":      ["revolution_revolve1",
                              "ice_boss_extrude1",
                              "cirpattern1"],
            "sourceFeatures":["Revolve1"],
            "confidence":    "high",
            "reviewed":      True,
            "requiresReview": False,   # curator dropped the review gate
            "editReadiness":  "ready", # and marked it ready
            "visualTargets":  {"glbNodes": ["revolution_revolve1"]},
            "cadTargets":     {"sourceFeatures": ["Revolve1"],
                               "upstreamFeatures": ["Sketch1"],
                               "sketches": ["Sketch1"],
                               "planes": ["Front Plane"],
                               "dimensions": ["D1@Sketch1"]},
            "editableParameters": [{"id": "D1@Sketch1", "unit": "mm"}],
            "notes":          "Locked + edit-ready.",
        }],
    }
    out.write_text(json.dumps(seed), encoding="utf-8")

    doc = build_draft_regions(aircraft_library, pn, rev)
    p = next(r for r in doc["regions"] if r["regionId"] == "propeller")
    # Everything the curator set survives verbatim
    assert p["requiresReview"] is False
    assert p["editReadiness"]  == "ready"
    assert p["cadTargets"]["sketches"]    == ["Sketch1"]
    assert p["cadTargets"]["planes"]      == ["Front Plane"]
    assert p["cadTargets"]["dimensions"]  == ["D1@Sketch1"]
    assert p["cadTargets"]["upstreamFeatures"] == ["Sketch1"]
    assert p["editableParameters"] == [{"id": "D1@Sketch1", "unit": "mm"}]


def test_build_draft_regions_schema_1_2_0_placement_scaffolding(aircraft_library: Path):
    """Schema 1.2.0 adds placementSurfaces (empty -- needs surface
    extractor) and placementCapabilities (default ["reference_only"]
    -- the honest MVP capability while no edit class is wired up).
    Every region must carry both fields with the seeded defaults."""
    doc = build_draft_regions(aircraft_library, "1030099", "revA")
    # Same anchor strategy as the 1.1.0 test: tie to the exported
    # constant so the assertion tracks future bumps automatically.
    assert doc["schemaVersion"] == SCHEMA_VERSION
    for r in doc["regions"]:
        # Placement surfaces seeded empty
        assert "placementSurfaces" in r
        assert r["placementSurfaces"] == [], \
            f"{r['regionId']} should ship with empty placementSurfaces in MVP"
        # Capabilities default to reference_only
        assert "placementCapabilities" in r
        assert r["placementCapabilities"] == ["reference_only"], \
            f"{r['regionId']} MVP capability set must be ['reference_only']; got {r['placementCapabilities']!r}"
        # Sanity: every reported capability is a known literal so a
        # future widening pass can't silently introduce typos.
        for cap in r["placementCapabilities"]:
            assert cap in PLACEMENT_CAPABILITIES, \
                f"{r['regionId']} unknown capability {cap!r}"


def test_placement_reserved_literals_are_exported_and_self_consistent():
    """The role / surfaceType / capability literal tuples are exported
    so downstream code (the future surface extractor, Sage edit
    planner) can pattern-match without restating strings. Smoke-check
    they include the user-facing spec values."""
    assert "primary_sketch_surface" in PLACEMENT_SURFACE_ROLES
    assert "reference_surface"      in PLACEMENT_SURFACE_ROLES
    assert "do_not_edit"            in PLACEMENT_SURFACE_ROLES
    assert "planar"                 in PLACEMENT_SURFACE_TYPES
    assert "cylindrical"            in PLACEMENT_SURFACE_TYPES
    assert "curved"                 in PLACEMENT_SURFACE_TYPES
    assert "unknown"                in PLACEMENT_SURFACE_TYPES
    for cap in ("sketch_on_face", "extruded_boss", "extruded_cut",
                "hole_wizard_pattern", "reference_only"):
        assert cap in PLACEMENT_CAPABILITIES, f"missing capability literal {cap}"


def test_upgrade_legacy_reviewed_region_to_1_2_0_seeds_placement_fields(aircraft_library: Path):
    """A reviewed region carried over from a pre-1.2.0 file lacks
    placementSurfaces / placementCapabilities. The upgrade chain
    must add both without disturbing curator content -- and a curator
    who has already populated either field keeps their values."""
    pn, rev = "1030099", "revA"
    out = semantic_regions_path(aircraft_library, pn, rev)
    out.parent.mkdir(parents=True, exist_ok=True)
    # Mix of two reviewed regions:
    #   - "propeller": pre-1.2.0 shape, NO placement fields
    #   - "top_wing":  curator already populated a sketch surface +
    #                  widened capabilities to include sketch_on_face
    legacy_doc = {
        "schemaVersion": "part-semantic-regions-1.1.0",
        "partNumber":    pn,
        "revision":      rev,
        "regions": [
            {
                "regionId":       "propeller",
                "label":          "Curated spinner",
                "aliases":        [],
                "glbNodes":       ["revolution_revolve1",
                                   "ice_boss_extrude1",
                                   "cirpattern1"],
                "sourceFeatures": ["Revolve1"],
                "confidence":     "high",
                "reviewed":       True,
                "notes":          "1.1.0-era curated region.",
            },
            {
                "regionId":           "top_wing",
                "label":              "Top wing (operator surfaces)",
                "aliases":            ["upper wing"],
                "glbNodes":           ["planarsurface_top_wing",
                                       "extrurefsurface_top_wing_root"],
                "sourceFeatures":     ["Top-Skin", "Top-Root"],
                "confidence":         "high",
                "reviewed":           True,
                "placementSurfaces":  [{
                    "faceId":        "FACE_001",
                    "sourceFeature": "Top-Skin",
                    "role":          "primary_sketch_surface",
                    "surfaceType":   "planar",
                    "normal":        [0.0, 1.0, 0.0],
                    "origin":        [0.0, 85.0, -140.0],
                    "xAxis":         [1.0, 0.0, 0.0],
                    "yAxis":         [0.0, 0.0, -1.0],
                    "span":          {"x": 500.0, "y": 100.0, "z": None, "unit": "mm"},
                    "safeMargins":   {"edge": 5.0},
                    "confidence":    "high",
                }],
                "placementCapabilities": ["sketch_on_face", "extruded_boss",
                                          "hole_wizard_pattern"],
                "notes":              "Curator placed top-skin sketch face.",
            },
        ],
    }
    out.write_text(json.dumps(legacy_doc), encoding="utf-8")

    doc = build_draft_regions(aircraft_library, pn, rev)
    by_id = {r["regionId"]: r for r in doc["regions"]}

    # Pre-1.2.0 propeller: placement fields seeded with defaults
    p = by_id["propeller"]
    assert p["reviewed"] is True, "curator review must survive"
    assert p["placementSurfaces"] == []
    assert p["placementCapabilities"] == ["reference_only"]

    # Curator-populated top_wing: placement fields PASS THROUGH
    # untouched (setdefault must not clobber non-empty curator data)
    tw = by_id["top_wing"]
    assert tw["reviewed"] is True
    assert len(tw["placementSurfaces"]) == 1
    surf = tw["placementSurfaces"][0]
    assert surf["faceId"]      == "FACE_001"
    assert surf["role"]        == "primary_sketch_surface"
    assert surf["surfaceType"] == "planar"
    assert surf["normal"]      == [0.0, 1.0, 0.0]
    assert tw["placementCapabilities"] == [
        "sketch_on_face", "extruded_boss", "hole_wizard_pattern"
    ], "curator-widened capabilities must not be reverted to reference_only"


def test_build_draft_regions_preserves_reviewed_true_regions(aircraft_library: Path):
    pn, rev = "1030099", "revA"
    # First draft -- nothing reviewed yet.
    doc1 = build_draft_regions(aircraft_library, pn, rev)
    write_semantic_regions(aircraft_library, pn, rev, doc1)
    # Operator manually marks the propeller region reviewed=true and
    # tweaks the label.
    out = semantic_regions_path(aircraft_library, pn, rev)
    existing = json.loads(out.read_text(encoding="utf-8"))
    for r in existing["regions"]:
        if r["regionId"] == "propeller":
            r["reviewed"] = True
            r["label"]    = "Spinner + 2-blade prop"
            r["notes"]    = "Operator-curated 2026-05-21."
            break
    out.write_text(json.dumps(existing), encoding="utf-8")

    # Re-draft. The reviewed region must carry over verbatim AND its
    # nodes must NOT be reassigned by the heuristic.
    doc2 = build_draft_regions(aircraft_library, pn, rev)
    propellers = [r for r in doc2["regions"] if r["regionId"] == "propeller"]
    assert len(propellers) == 1, "no duplicate propeller region across re-draft"
    assert propellers[0]["reviewed"]   is True
    assert propellers[0]["label"]      == "Spinner + 2-blade prop"
    assert propellers[0]["notes"]      == "Operator-curated 2026-05-21."
    # And the propeller's glbNodes never appear elsewhere.
    propeller_nodes = set(propellers[0]["glbNodes"])
    for r in doc2["regions"]:
        if r["regionId"] == "propeller":
            continue
        leak = propeller_nodes & set(r["glbNodes"])
        assert not leak, f"reviewed propeller nodes leaked into {r['regionId']!r}: {leak}"
    # And the locked-nodes field reflects what was preserved.
    assert set(doc2["summary"]["lockedNodes"]) == propeller_nodes


def test_build_draft_regions_solid_only_uses_fallback_buckets(solid_only_library: Path):
    doc = build_draft_regions(solid_only_library, "1020099", "revA")
    region_ids = {r["regionId"] for r in doc["regions"]}
    # No aircraft-shape rule should fire on a compact solid part.
    aircraft_ids = {"propeller", "top_wing", "lower_wing",
                    "tail_horizontal_stabilizer", "tail_vertical_stabilizer",
                    "tail_other", "strut_outer", "strut_inner"}
    overlap = region_ids & aircraft_ids
    assert not overlap, f"solid-only fixture should not trip aircraft rules; got {overlap}"
    # All assigned buckets are name-based fallbacks.
    for rid in region_ids:
        assert rid.startswith("features_") or rid == "fuselage_candidate", \
            f"unexpected region id for solid-only fixture: {rid}"
    # Every region marked low confidence + unreviewed.
    for r in doc["regions"]:
        assert r["confidence"] == "low"
        assert r["reviewed"]   is False


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------

def test_GET_part_semantic_regions_404_when_absent(aircraft_library: Path):
    client = TestClient(server.app)
    r = client.get("/api/part-semantic-regions/1030099", params={"revision": "A"})
    assert r.status_code == 404
    assert "POST" in r.json()["detail"], "404 message should hint at the draft endpoint"


def test_POST_draft_creates_file_and_GET_returns_it(aircraft_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/part-semantic-regions/1030099/draft", json={"revision": "A"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["partNumber"] == "1030099"
    assert body["revision"]   == "revA"
    assert body["schemaVersion"] == SCHEMA_VERSION
    # File must actually exist on disk
    out_path = Path(body["outputPath"])
    assert out_path.exists()
    # GET returns the same document
    g = client.get("/api/part-semantic-regions/1030099", params={"revision": "revA"})
    assert g.status_code == 200, g.text
    assert g.json()["schemaVersion"] == SCHEMA_VERSION


def test_POST_draft_404_when_GLB_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """No GLB on disk -> 404 + actionable error message pointing at
    Enrich Visuals."""
    library = tmp_path / "lib"
    (library / "parts" / "1030099" / "revA").mkdir(parents=True)
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    client = TestClient(server.app)
    r = client.post("/api/part-semantic-regions/1030099/draft", json={"revision": "A"})
    assert r.status_code == 404
    assert "Enrich Visuals" in r.json()["detail"]


def test_POST_draft_accepts_both_revA_and_A(aircraft_library: Path):
    """The endpoint normalises both 'revA' and 'A' to 'revA'."""
    client = TestClient(server.app)
    r1 = client.post("/api/part-semantic-regions/1030099/draft", json={"revision": "A"})
    r2 = client.post("/api/part-semantic-regions/1030099/draft", json={"revision": "revA"})
    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r1.json()["revision"] == "revA"
    assert r2.json()["revision"] == "revA"


def test_POST_draft_rejects_invalid_revision(aircraft_library: Path):
    client = TestClient(server.app)
    r = client.post("/api/part-semantic-regions/1030099/draft", json={"revision": "rev_A"})
    assert r.status_code == 400


def test_POST_draft_idempotent_after_review(aircraft_library: Path):
    """Lock a region (reviewed=true), re-post, confirm preservation
    flows through the HTTP layer too."""
    client = TestClient(server.app)
    r = client.post("/api/part-semantic-regions/1030099/draft", json={"revision": "A"})
    assert r.status_code == 200
    # Mark top_wing reviewed via direct file edit (the curator UI is
    # a separate work item; this test just simulates it).
    out_path = Path(r.json()["outputPath"])
    doc = json.loads(out_path.read_text(encoding="utf-8"))
    for region in doc["regions"]:
        if region["regionId"] == "top_wing":
            region["reviewed"] = True
            region["label"]    = "Curated top wing"
            break
    out_path.write_text(json.dumps(doc), encoding="utf-8")
    # Re-post the draft.
    r2 = client.post("/api/part-semantic-regions/1030099/draft", json={"revision": "A"})
    assert r2.status_code == 200, r2.text
    top_regions = [reg for reg in r2.json()["regions"] if reg["regionId"] == "top_wing"]
    assert len(top_regions) == 1
    assert top_regions[0]["reviewed"] is True
    assert top_regions[0]["label"]    == "Curated top wing"


# ---------------------------------------------------------------------------
# Live 1030034 sanity check (read-only, skips when the library isn't
# available -- e.g. on a CI runner without the assets).
# ---------------------------------------------------------------------------

def _live_library_path() -> Path:
    """Resolve the same library server.LIBRARY_DIR would point at."""
    return server._resolve_library_dir()


def _has_live_part(pn: str, rev: str) -> bool:
    lib = _live_library_path()
    return (lib / "parts" / pn / rev / f"{pn}_colored.glb").exists()


@pytest.mark.skipif(not _has_live_part("1030034", "revB"),
                    reason="live 1030034 revB GLB not available in the resolved library")
def test_live_1030034_revB_produces_expected_aircraft_regions(tmp_path: Path):
    """End-to-end: real 1030034 revB GLB must classify into the
    aircraft regions we predicted in the design pass. Skips when the
    asset is missing so this works in CI without the library. We
    write the OUTPUT into tmp_path so the live library isn't mutated."""
    live_lib = _live_library_path()
    pn, rev  = "1030034", "revB"

    # Build against the LIVE glb -- but route the output write to a
    # private tmp library so we never touch the real library file.
    doc = build_draft_regions(live_lib, pn, rev)
    region_ids = {r["regionId"] for r in doc["regions"]}
    expected = {
        "propeller",
        "top_wing",
        "lower_wing",
        "tail_horizontal_stabilizer",
        "tail_vertical_stabilizer",
        "fuselage_candidate",
    }
    missing = expected - region_ids
    assert not missing, f"live 1030034 revB missing expected regions: {missing}"

    # Reality-check: every node assigned exactly once.
    counts: dict = {}
    for r in doc["regions"]:
        for n in r["glbNodes"]:
            counts[n] = counts.get(n, 0) + 1
    dupes = [n for n, c in counts.items() if c > 1]
    assert not dupes, f"live 1030034 nodes assigned to multiple regions: {dupes}"
    # Match the inspector's node count from the design pass (29).
    assert doc["summary"]["totalNodes"] == 29, \
        f"expected 29 nodes in 1030034 revB GLB, got {doc['summary']['totalNodes']}"
