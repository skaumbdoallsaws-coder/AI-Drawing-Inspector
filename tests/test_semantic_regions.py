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
    MATCH_KINDS,
    PLACEMENT_CAPABILITIES,
    PLACEMENT_SURFACE_ROLES,
    PLACEMENT_SURFACE_TYPES,
    ResolvedRegion,
    SCHEMA_VERSION,
    build_draft_regions,
    resolve_region_for_phrase,
    resolve_regions_for_phrases,
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
    # Minimal feature_colors.json so sourceFeatures populates. Use the
    # REAL snake_case schema the SolidWorksExtractor writes
    # (glb_node_name + sw_name + cad_feature_id) -- not the camelCase
    # variant -- so the loader is tested against on-disk reality.
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
                  "placementSurfaces", "placementCapabilities",
                  # 1.3.0 traceability
                  "unmappedGlbNodes"):
            assert k in r, f"region {r.get('regionId')!r} missing {k}"
        assert r["reviewed"] is False, "new drafts must always start unreviewed"
        assert r["confidence"] in ("low", "medium", "high")


def test_build_draft_regions_sourceFeatures_populated_from_feature_colors(aircraft_library: Path):
    """Test #1: region.sourceFeatures populates from feature_colors.json
    via the glb_node_name lookup. The fixture writes sw_name as the
    Title Case form of the glb_node_name, so we can assert the exact
    transformation flowed through."""
    doc = build_draft_regions(aircraft_library, "1030099", "revA")
    propeller = next(r for r in doc["regions"] if r["regionId"] == "propeller")
    # Every propeller glbNode resolves to a sw_name
    assert len(propeller["sourceFeatures"]) == len(propeller["glbNodes"]), \
        (f"every propeller glbNode should resolve to a sw_name; "
         f"got {propeller['sourceFeatures']} for {propeller['glbNodes']}")
    # feature_colors fixture wrote sw_name = Title(glb_node_name.replace('_',' '))
    # so revolution_revolve1 -> "Revolution Revolve1"
    assert "Revolution Revolve1" in propeller["sourceFeatures"]
    # The region must have NO unmapped nodes when the sidecar is complete
    assert propeller["unmappedGlbNodes"] == []


def test_build_draft_regions_cadTargets_mirrors_sourceFeatures(aircraft_library: Path):
    """Test #2: cadTargets.sourceFeatures must mirror the resolved
    SW feature names AND cadTargets.cadFeatureIds carries the stable
    SolidWorks identifiers (cad_feature_id) for the future Sage bridge."""
    doc = build_draft_regions(aircraft_library, "1030099", "revA")
    for r in doc["regions"]:
        ct = r["cadTargets"]
        assert ct["sourceFeatures"] == r["sourceFeatures"], \
            f"{r['regionId']} cadTargets.sourceFeatures must mirror top-level sourceFeatures"
        # cadFeatureIds carries the stable CAD identifiers. The
        # fixture sets cad_feature_id == glb_node_name, so for any
        # mapped node we should see the node name in cadFeatureIds.
        mapped_count = len(r["glbNodes"]) - len(r["unmappedGlbNodes"])
        assert len(ct["cadFeatureIds"]) == mapped_count, \
            (f"{r['regionId']} cadTargets.cadFeatureIds length should match "
             f"the count of MAPPED glbNodes (got {len(ct['cadFeatureIds'])} "
             f"for {mapped_count} mapped of {len(r['glbNodes'])} total)")
        # And every cadFeatureId in the region should be one of the
        # region's mapped glbNodes (in this fixture they're equal).
        mapped_glb = [n for n in r["glbNodes"] if n not in set(r["unmappedGlbNodes"])]
        assert ct["cadFeatureIds"] == mapped_glb, \
            (f"{r['regionId']} cadFeatureIds drift from mapped glbNodes: "
             f"{ct['cadFeatureIds']} vs {mapped_glb}")


def test_build_draft_regions_unmapped_nodes_do_not_crash(aircraft_library: Path):
    """Test #3: a glbNode with no feature_colors mapping must not
    crash the builder. The node still appears in glbNodes /
    visualTargets.glbNodes (so the UI can highlight it) and is
    reported in unmappedGlbNodes with a review note in `notes`."""
    # Remove the feature_colors entry for the propeller's revolve,
    # mirroring the real-world case where the bridge sidecar gets
    # out of sync with the GLB.
    pn, rev = "1030099", "revA"
    fcp = aircraft_library / "parts" / pn / rev / f"{pn}_feature_colors.json"
    doc = json.loads(fcp.read_text(encoding="utf-8"))
    doc["features"] = [f for f in doc["features"]
                       if f.get("glb_node_name") != "revolution_revolve1"]
    fcp.write_text(json.dumps(doc), encoding="utf-8")

    out = build_draft_regions(aircraft_library, pn, rev)
    propeller = next(r for r in out["regions"] if r["regionId"] == "propeller")
    # Node still listed for highlighting
    assert "revolution_revolve1" in propeller["glbNodes"]
    assert "revolution_revolve1" in propeller["visualTargets"]["glbNodes"]
    # And reported as unmapped
    assert "revolution_revolve1" in propeller["unmappedGlbNodes"]
    # SourceFeatures shrank by exactly one (the unmapped node)
    assert len(propeller["sourceFeatures"]) == len(propeller["glbNodes"]) - 1
    # Notes carries the review pointer
    assert "unmappedGlbNodes" in propeller["notes"], \
        f"notes should hint at the unmapped nodes; got {propeller['notes']!r}"


def test_build_draft_regions_curator_sourceFeatures_not_clobbered(aircraft_library: Path):
    """Test #4: when a curator has marked a region reviewed=true and
    populated sourceFeatures by hand, re-drafting must NOT replace
    those values with the auto-resolved sw_names from feature_colors.
    The preservation path copies reviewed regions verbatim before the
    builder touches them."""
    pn, rev = "1030099", "revA"
    # First draft creates the file
    doc1 = build_draft_regions(aircraft_library, pn, rev)
    write_semantic_regions(aircraft_library, pn, rev, doc1)
    # Curator manually rewrites the propeller's sourceFeatures with
    # human-friendly labels that DON'T match the auto-resolution
    out = semantic_regions_path(aircraft_library, pn, rev)
    existing = json.loads(out.read_text(encoding="utf-8"))
    for r in existing["regions"]:
        if r["regionId"] == "propeller":
            r["reviewed"] = True
            r["sourceFeatures"] = [
                "Curator: spinner cap",
                "Curator: leading blade",
                "Curator: blade pattern",
            ]
            r["cadTargets"]["sourceFeatures"] = list(r["sourceFeatures"])
            r["cadTargets"]["cadFeatureIds"]  = ["CURATED_FACE_001", "CURATED_FACE_002"]
            break
    out.write_text(json.dumps(existing), encoding="utf-8")

    # Re-draft -- propeller must come back UNCHANGED
    doc2 = build_draft_regions(aircraft_library, pn, rev)
    propeller = next(r for r in doc2["regions"] if r["regionId"] == "propeller")
    assert propeller["reviewed"] is True
    assert propeller["sourceFeatures"] == [
        "Curator: spinner cap",
        "Curator: leading blade",
        "Curator: blade pattern",
    ], "curator sourceFeatures must not be replaced by auto-resolution"
    assert propeller["cadTargets"]["sourceFeatures"] == propeller["sourceFeatures"]
    assert propeller["cadTargets"]["cadFeatureIds"]  == ["CURATED_FACE_001", "CURATED_FACE_002"], \
        "curator-set cadFeatureIds must survive re-draft"


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


# ---------------------------------------------------------------------------
# Phrase resolver
# ---------------------------------------------------------------------------

@pytest.fixture
def aircraft_library_with_draft(aircraft_library: Path) -> Path:
    """Same fixture as aircraft_library, but with the draft regions
    file already persisted on disk so the resolver has something to
    read against."""
    pn, rev = "1030099", "revA"
    doc = build_draft_regions(aircraft_library, pn, rev)
    write_semantic_regions(aircraft_library, pn, rev, doc)
    return aircraft_library


def test_resolver_top_wing_resolves_to_regionId(aircraft_library_with_draft: Path):
    """Per spec test #1: 'top wing' resolves to regionId top_wing.

    Normalization collapses 'top_wing' and 'top wing' to the same
    string, so the regionId-exact pass fires first (before the
    label pass). The matchKind reflects WHICH lookup hit, not the
    surface form -- both 'top wing' and 'top_wing' route to
    matchKind='regionId' because the normalized region id matches
    the normalized phrase. Either way the caller gets the same
    region back."""
    hit = resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA", "top wing")
    assert hit is not None, "phrase 'top wing' must resolve"
    assert hit.regionId == "top_wing"
    assert hit.label    == "Top wing"
    assert hit.matchKind == "regionId", \
        f"expected regionId match (normalization collapses 'top_wing' == 'top wing'); got {hit.matchKind}"
    assert hit.matchedAlias is None
    assert hit.matchKind in MATCH_KINDS


def test_resolver_alias_upper_wing_resolves(aircraft_library_with_draft: Path):
    """Per spec test #2: aliases like 'upper wing' resolve to the
    canonical region. LABELS map declares 'upper wing' as a top_wing
    alias, so this is the alias-exact path."""
    hit = resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA", "upper wing")
    assert hit is not None, "alias 'upper wing' must resolve"
    assert hit.regionId    == "top_wing"
    assert hit.matchKind   == "alias"
    assert hit.matchedAlias == "upper wing"


def test_resolver_returns_visualTargets_and_cadFeatureIds(aircraft_library_with_draft: Path):
    """Per spec test #3: returned highlight IDs include the GLB node
    names for the matched region. Synthetic fixture top_wing contains
    planarsurface_top_wing + extrurefsurface_top_wing_root (both
    qualify under the wing rule due to their lateral extent)."""
    hit = resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA", "top wing")
    assert hit is not None
    assert hit.glbNodes, "glbNodes must not be empty for top_wing"
    # The synthetic fixture's top_wing region groups the planar top
    # surface (the wide-span body the heuristic catches). cad ids
    # mirror glb node names because the fixture sets cad_feature_id
    # equal to glb_node_name.
    assert "planarsurface_top_wing" in hit.glbNodes
    assert hit.cadFeatureIds, "cadFeatureIds must not be empty when feature_colors maps"
    assert "planarsurface_top_wing" in hit.cadFeatureIds


def test_resolver_unknown_phrase_falls_back_cleanly(aircraft_library_with_draft: Path):
    """Per spec test #4: an unknown phrase returns None rather than
    crashing OR fuzzy-matching into an unrelated region. Highlight
    pipeline can treat None as 'nothing to highlight via semantic
    regions; let other paths take over.'"""
    assert resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA",
        "completely made up part name xyzzy") is None
    # Also confirm graceful behavior on edge inputs
    assert resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA", "") is None
    assert resolve_region_for_phrase(  # type: ignore[arg-type]
        aircraft_library_with_draft, "1030099", "revA", None) is None


def test_resolver_handles_underscore_phrase(aircraft_library_with_draft: Path):
    """User OR Sage may emit either 'top wing' or 'top_wing' -- both
    must resolve. Whitespace / underscore / hyphen all normalize to
    a single space before matching."""
    hit_underscore = resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA", "top_wing")
    hit_hyphen     = resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA", "top-wing")
    hit_caps       = resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA", "TOP WING")
    assert hit_underscore is not None and hit_underscore.regionId == "top_wing"
    assert hit_hyphen     is not None and hit_hyphen.regionId     == "top_wing"
    assert hit_caps       is not None and hit_caps.regionId       == "top_wing"


def test_resolver_substring_match_on_longer_phrase(aircraft_library_with_draft: Path):
    """A natural-language phrase ('show me the upper wing') should
    still resolve via substring match against the 'upper wing' alias."""
    hit = resolve_region_for_phrase(
        aircraft_library_with_draft, "1030099", "revA",
        "show me the upper wing")
    assert hit is not None
    assert hit.regionId  == "top_wing"
    assert hit.matchKind in ("alias", "alias_substring")


def test_resolver_returns_none_when_draft_file_missing(aircraft_library: Path):
    """No draft file on disk yet -> resolver must return None silently
    so the highlight pipeline falls back to other paths instead of
    crashing."""
    # aircraft_library fixture does NOT write the draft file.
    assert resolve_region_for_phrase(
        aircraft_library, "1030099", "revA", "top wing") is None


def test_resolve_regions_for_phrases_dedupes_same_region(aircraft_library_with_draft: Path):
    """Multiple phrases pointing at the same region collapse to a
    single ResolvedRegion in the output, preserving first-occurrence
    order across distinct hits."""
    out = resolve_regions_for_phrases(
        aircraft_library_with_draft, "1030099", "revA",
        ["top wing", "upper wing", "main upper wing", "propeller"])
    region_ids = [r.regionId for r in out]
    assert region_ids == ["top_wing", "propeller"], \
        f"expected dedupe to top_wing + propeller in order, got {region_ids}"


# ---------------------------------------------------------------------------
# HTTP /resolve endpoint
# ---------------------------------------------------------------------------

def test_GET_resolve_endpoint_returns_match(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    r = client.get("/api/part-semantic-regions/1030099/resolve",
                   params={"revision": "A", "phrase": "top wing"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matched"]       is True
    assert body["regionId"]      == "top_wing"
    assert body["matchKind"]     == "regionId"
    assert "planarsurface_top_wing" in body["glbNodes"]
    assert "planarsurface_top_wing" in body["cadFeatureIds"]


def test_GET_resolve_endpoint_404_when_no_match(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    r = client.get("/api/part-semantic-regions/1030099/resolve",
                   params={"revision": "A", "phrase": "xyzzy"})
    assert r.status_code == 404
    body = r.json()
    assert body["matched"] is False
    assert "xyzzy" in body["detail"]


def test_GET_resolve_endpoint_400_when_phrase_blank(aircraft_library_with_draft: Path):
    client = TestClient(server.app)
    r = client.get("/api/part-semantic-regions/1030099/resolve",
                   params={"revision": "A", "phrase": "   "})
    assert r.status_code == 400


def test_GET_resolve_endpoint_404_when_draft_missing(aircraft_library: Path):
    """No draft on disk -> 404 (not 500); body says matched=false."""
    client = TestClient(server.app)
    r = client.get("/api/part-semantic-regions/1030099/resolve",
                   params={"revision": "A", "phrase": "top wing"})
    assert r.status_code == 404
    assert r.json()["matched"] is False


# ---------------------------------------------------------------------------
# Existing HIGHLIGHT_FEATURES behavior preserved
# ---------------------------------------------------------------------------

def test_existing_highlight_features_parser_unchanged():
    """Regression guard: the HIGHLIGHT_FEATURES regex + fuzzy fallback
    block must still be intact and reachable. We assert the literal
    strings the agent loop depends on, NOT the marker presence (which
    is exercised by the broader agent suite). If someone renames the
    marker or removes the fuzzy fallback this test fires."""
    import inspect
    src = inspect.getsource(server)
    # Marker regex
    assert "HIGHLIGHT_FEATURES?:" in src, \
        "HIGHLIGHT_FEATURES marker regex must remain in server.py"
    # Fuzzy fallback identifiers
    assert "available_cad_features" in src, \
        "HIGHLIGHT_FEATURES still validates against ctx.available_cad_features"
    # The new HIGHLIGHT_REGIONS marker exists alongside, NOT replacing
    assert "HIGHLIGHT_REGIONS:" in src, \
        "HIGHLIGHT_REGIONS marker must be wired in server.py"
    # And the response payload carries the new field name (defensive --
    # frontend pass-through depends on this exact key).
    assert '"highlight_regions"' in src or "highlight_regions" in src


# ---------------------------------------------------------------------------
# Integration: HIGHLIGHT_REGIONS folds resolved cadFeatureIds into the
# existing highlight_features pipeline so the existing frontend tool
# registry (which only consumes highlight_features) actually lights up
# the 3D viewer. Drives /api/agent/chat end-to-end with a stubbed
# Anthropic client so we exercise the real marker parser + the canonical
# build_tool_calls_from_result reduction.
# ---------------------------------------------------------------------------

class _StubBlock:
    def __init__(self, text: str):
        self.text = text


class _StubResponse:
    def __init__(self, text: str):
        self.content = [_StubBlock(text)]
        # build_tool_calls_from_result + telemetry both probe a small
        # set of attributes; expose the defaults the real Messages
        # response uses so nothing downstream raises AttributeError.
        self.usage         = None
        self.stop_reason   = "end_turn"
        self.stop_sequence = None
        self.model         = "stub"


class _StubMessages:
    def __init__(self, text: str):
        self._text = text
        self.last_kwargs = None

    def create(self, **kwargs):
        self.last_kwargs = kwargs
        return _StubResponse(self._text)


class _StubAnthropic:
    """Drop-in replacement for anthropic.Anthropic used by /api/agent/chat.
    Whatever text the test passes via _stub_anthropic_response() is what
    the marker parser will see -- the regex + resolver + dedupe path is
    exercised for real."""
    def __init__(self, *args, **kwargs):
        self.messages = _StubAnthropic._messages_for_test


def _stub_anthropic_response(monkeypatch: pytest.MonkeyPatch, response_text: str) -> _StubMessages:
    import anthropic
    msgs = _StubMessages(response_text)
    _StubAnthropic._messages_for_test = msgs  # type: ignore[attr-defined]
    monkeypatch.setattr(anthropic, "Anthropic", _StubAnthropic)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-stub-key-not-real")
    return msgs


def _inspection_ctx_with_features(pn: str, revision: str) -> dict:
    """Build a minimal inspection_context dict that lets the marker
    parser validate HIGHLIGHT_FEATURES against available_cad_features.
    The IDs mirror the synthetic aircraft fixture's mesh names so a
    region's cadFeatureIds resolve to real entries."""
    feature_ids = [n for n, *_ in _aircraft_fixture()]
    return {
        "part_number": pn,
        "revision":    revision,
        "available_cad_features": [
            {"cad_feature_id": fid, "display_label": fid, "type": fid.split("_", 1)[0],
             "color_name": "blue", "face_count": 1}
            for fid in feature_ids
        ],
    }


def test_HIGHLIGHT_REGIONS_folds_cadFeatureIds_into_highlight_features(
    aircraft_library_with_draft: Path, monkeypatch: pytest.MonkeyPatch
):
    """Per reviewer spec: when Sage emits HIGHLIGHT_REGIONS: top wing,
    the resolver returns the top_wing region; its cadFeatureIds
    (planarsurface_top_wing, extrurefsurface_top_wing_root) MUST end
    up in result.highlight_features so the existing frontend tool
    registry actually highlights the 3D model. The highlight_regions
    metadata is also present for the future CAD bridge."""
    _stub_anthropic_response(monkeypatch,
        "The top wing extends across the full span.\n"
        "HIGHLIGHT_REGIONS: top wing\n"
    )
    client = TestClient(server.app)
    r = client.post("/api/agent/chat", json={
        "message":            "show me the top wing",
        "agent_type":         "deviation-analyst",
        "inspection_context": _inspection_ctx_with_features("1030099", "revA"),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    # Metadata pass-through: regions present
    assert "highlight_regions" in body, body
    assert any(reg.get("regionId") == "top_wing" for reg in body["highlight_regions"])
    # Integration fold: cadFeatureIds appear in the feature highlight list
    # that the existing tool pipeline actually consumes.
    assert "highlight_features" in body, \
        "HIGHLIGHT_REGIONS must fold region cadFeatureIds into highlight_features"
    assert "planarsurface_top_wing" in body["highlight_features"]


def test_HIGHLIGHT_FEATURES_alone_still_works(
    aircraft_library_with_draft: Path, monkeypatch: pytest.MonkeyPatch
):
    """Regression: the original HIGHLIGHT_FEATURES marker (no
    HIGHLIGHT_REGIONS) keeps producing highlight_features exactly as
    before, and does NOT produce a stray highlight_regions field."""
    _stub_anthropic_response(monkeypatch,
        "Here is the propeller revolve.\n"
        "HIGHLIGHT_FEATURES: revolution_revolve1\n"
    )
    client = TestClient(server.app)
    r = client.post("/api/agent/chat", json={
        "message":            "show me the propeller revolve",
        "agent_type":         "deviation-analyst",
        "inspection_context": _inspection_ctx_with_features("1030099", "revA"),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("highlight_features") == ["revolution_revolve1"]
    assert "highlight_regions" not in body, \
        "no HIGHLIGHT_REGIONS in response -> no highlight_regions field"


def test_HIGHLIGHT_FEATURES_plus_HIGHLIGHT_REGIONS_dedupes(
    aircraft_library_with_draft: Path, monkeypatch: pytest.MonkeyPatch
):
    """When Sage emits BOTH markers AND there is overlap (the explicit
    feature ID is also one of the region's cadFeatureIds), the final
    highlight_features list must dedupe -- not contain
    planarsurface_top_wing twice. The top_wing region in the synthetic
    fixture happens to contain exactly one cadFeatureId
    (planarsurface_top_wing) because the wing rule's lateral-span gate
    only catches the wide planar surface; this means HIGHLIGHT_FEATURES
    and HIGHLIGHT_REGIONS overlap fully on this entry and the test can
    assert the deduped list IS [planarsurface_top_wing]."""
    _stub_anthropic_response(monkeypatch,
        "Highlighting the planar top surface and the wider top wing.\n"
        "HIGHLIGHT_FEATURES: planarsurface_top_wing\n"
        "HIGHLIGHT_REGIONS: top wing\n"
    )
    client = TestClient(server.app)
    r = client.post("/api/agent/chat", json={
        "message":            "show me the top wing surfaces",
        "agent_type":         "deviation-analyst",
        "inspection_context": _inspection_ctx_with_features("1030099", "revA"),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    hf = body.get("highlight_features", [])
    # Dedupe: planarsurface_top_wing must appear EXACTLY once.
    assert hf.count("planarsurface_top_wing") == 1, \
        f"expected planarsurface_top_wing to appear once after dedupe, got {hf}"
    # Region metadata still attached.
    assert any(reg.get("regionId") == "top_wing"
               for reg in body.get("highlight_regions", []))


def test_HIGHLIGHT_FEATURES_plus_HIGHLIGHT_REGIONS_unions_distinct(
    aircraft_library_with_draft: Path, monkeypatch: pytest.MonkeyPatch
):
    """When the two markers contribute DISJOINT features, the final
    highlight_features list is the union with original-order preserved
    (HIGHLIGHT_FEATURES entries first, then region-derived entries).
    HIGHLIGHT_FEATURES: revolution_revolve1 (propeller, not in any
    wing region). HIGHLIGHT_REGIONS: top wing -> adds
    planarsurface_top_wing. Result: both must appear, both exactly
    once, propeller first."""
    _stub_anthropic_response(monkeypatch,
        "Highlighting the propeller revolve and the top wing.\n"
        "HIGHLIGHT_FEATURES: revolution_revolve1\n"
        "HIGHLIGHT_REGIONS: top wing\n"
    )
    client = TestClient(server.app)
    r = client.post("/api/agent/chat", json={
        "message":            "show me the propeller and the top wing",
        "agent_type":         "deviation-analyst",
        "inspection_context": _inspection_ctx_with_features("1030099", "revA"),
    })
    assert r.status_code == 200, r.text
    body = r.json()
    hf = body.get("highlight_features", [])
    assert hf.count("revolution_revolve1") == 1
    assert hf.count("planarsurface_top_wing") == 1
    # Order: HIGHLIGHT_FEATURES parsed first, region-derived appended after.
    assert hf.index("revolution_revolve1") < hf.index("planarsurface_top_wing"), \
        f"expected HIGHLIGHT_FEATURES entries before region-derived entries, got {hf}"


def test_AVAILABLE_SEMANTIC_REGIONS_section_injected_into_context(
    aircraft_library_with_draft: Path
):
    """When a semantic-regions draft exists for the active part/rev,
    _build_context_message must inject an AVAILABLE SEMANTIC REGIONS
    section so Sage knows what phrases it can emit. The section
    lists regionId + label + aliases and the HIGHLIGHT_REGIONS
    marker instruction."""
    ctx_msg = server._build_context_message({
        "part_number": "1030099",
        "revision":    "revA",
    })
    assert "AVAILABLE SEMANTIC REGIONS" in ctx_msg, ctx_msg
    assert "HIGHLIGHT_REGIONS:" in ctx_msg
    # Top wing region from the synthetic fixture must be present.
    assert "top_wing" in ctx_msg
    # Aliases are surfaced so the model can use natural phrases.
    assert "upper wing" in ctx_msg


def test_AVAILABLE_SEMANTIC_REGIONS_section_absent_when_no_draft(
    aircraft_library: Path
):
    """No draft file on disk -> the AVAILABLE SEMANTIC REGIONS block
    must not appear (silent skip, never crash). Keeps the prompt
    short when there is nothing useful to add."""
    ctx_msg = server._build_context_message({
        "part_number": "1030099",
        "revision":    "revA",
    })
    assert "AVAILABLE SEMANTIC REGIONS" not in ctx_msg


def test_SAGE_prompt_documents_HIGHLIGHT_REGIONS_marker():
    """The deviation-analyst system prompt must teach the model about
    HIGHLIGHT_REGIONS so it actually emits the marker in production.
    Without this, the resolver path is dead code."""
    prompt = server.AGENT_PROMPTS.get("deviation-analyst", "")
    assert "HIGHLIGHT_REGIONS" in prompt, \
        "deviation-analyst prompt must mention HIGHLIGHT_REGIONS"
    assert "semantic region" in prompt.lower(), \
        "prompt should explain what a semantic region is"
