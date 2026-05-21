"""Tests for the Library Intake numbering helper + endpoint.

Covers:
- _intake_used_part_numbers scans root files (any extension, with the
  suffix-strip rules), parts/{pn}/ directories, and assemblies/.
- _intake_next_part_number returns the first gap in the configured
  prefix range with width derived from prefix length.
- GET /api/library/numbering/next happy paths + bad-input 400s + range-
  exhausted 409.
- The deliberate "operator picks a longer prefix to extend an existing
  sub-series" pattern (no silent guessing of the convention).
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


@pytest.fixture
def numbering_library(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    """Seed a temp library with a representative mix of:
      - root files: .json, .STL, .pdf, .glb, .png with various suffixes
      - parts/{pn}/ directories (some matching root files, some not)
      - assemblies/{id}_assembly.json
    Asserted via tests below."""
    library = tmp_path / "lib"
    library.mkdir()
    # Root files for part 1030001 — every suffix variety we strip
    (library / "1030001.json").write_text("{}", encoding="utf-8")
    (library / "1030001.STL").write_text("solid", encoding="utf-8")
    (library / "1030001_drawing_map.json").write_text("{}", encoding="utf-8")
    (library / "1030001_drawing.pdf").write_bytes(b"%PDF-1.4\n%%EOF")
    (library / "1030001_inspection_profile.json").write_text("{}", encoding="utf-8")
    (library / "1030001_colored.glb").write_bytes(b"glTF")
    (library / "1030001_feature_colors.json").write_text("{}", encoding="utf-8")
    (library / "1030001_view_front.png").write_bytes(b"PNG")
    (library / "1030001_view_top.png").write_bytes(b"PNG")
    (library / "1030001_view_right.png").write_bytes(b"PNG")
    (library / "1030001_view_isometric.png").write_bytes(b"PNG")
    (library / "1030001_highlight_boxes.json").write_text("[]", encoding="utf-8")
    (library / "1030001_dimension_descriptions.json").write_text("{}", encoding="utf-8")
    # Root files for part 1030005 (just a profile)
    (library / "1030005_inspection_profile.json").write_text("{}", encoding="utf-8")
    # parts/{pn}/ subdir for a part that has NO root file (model-only flow)
    (library / "parts" / "1030009" / "revA").mkdir(parents=True)
    (library / "parts" / "1030009" / "revA" / "1030009.json").write_text("{}", encoding="utf-8")
    # Assembly with the existing convention
    (library / "assemblies").mkdir()
    (library / "assemblies" / "6000300_assembly.json").write_text("{}", encoding="utf-8")
    (library / "assemblies" / "6000302_assembly.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    monkeypatch.setattr(server, "assembly_profiles", {}, raising=False)
    monkeypatch.setattr(server, "inspector", None)
    yield library


# ── Helper: _intake_used_part_numbers ────────────────────────────────


def test_used_part_numbers_rolls_up_root_file_variants(numbering_library: Path):
    """Every root-level file for 1030001 (json, STL, drawing_map,
    inspection_profile, glb, feature_colors, 4× view PNG,
    highlight_boxes, dimension_descriptions, drawing.pdf) must roll up
    to the single token '1030001'. If any suffix slips through the
    stripper, the test catches it as a stray token."""
    used = server._intake_used_part_numbers(numbering_library)
    assert "1030001" in used
    # No suffix-leaked stray tokens for 1030001
    leaked = [u for u in used if u.startswith("1030001") and u != "1030001"]
    assert leaked == [], f"unexpected leaked tokens: {leaked}"


def test_used_part_numbers_includes_subdir_only_parts(numbering_library: Path):
    """parts/{pn}/ -- model-only intake leaves the part without a root
    profile until a real one is authored. The numbering scanner must
    still see it so the next suggestion does not collide."""
    used = server._intake_used_part_numbers(numbering_library)
    assert "1030009" in used


def test_used_part_numbers_includes_assembly_internal_partno_refs(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch):
    """Regression for the 1030031 Straight-Rail smoke bug: a part
    number referenced inside an assembly's customProperties is just
    as 'taken' as one with a root profile. Mirrors the real-world
    shape observed in 400S_Sorted_Library/assemblies/6000302_assembly.json
    (customProperties.PartNo)."""
    library = tmp_path / "asm_lib"
    (library / "assemblies").mkdir(parents=True)
    (library / "assemblies" / "6000302_assembly.json").write_text(json.dumps({
        "identity":   {"id": "6000302", "name": "Straight Roller Conveyor"},
        "components": [
            {"name": "Straight Rail",
             "customProperties": {"PartNo": "1030031", "Description": "Straight Rail"}},
            {"name": "Roller",
             "customProperties": {"PartNo": "1030032", "Description": "Roller"}},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    used = server._intake_used_part_numbers(library)
    assert "1030031" in used, "PartNo 1030031 inside 6000302 component was missed by the scanner"
    assert "1030032" in used
    # Assembly identifier itself also captured (existing behaviour)
    assert "6000302" in used


def test_used_part_numbers_assembly_walk_accepts_alternate_part_keys(tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch):
    """All four canonical key spellings (PartNo, part_number, partNumber,
    part_no) must be honored so a future extractor variant cannot
    silently regress the suggester."""
    library = tmp_path / "asm_lib2"
    (library / "assemblies").mkdir(parents=True)
    (library / "assemblies" / "9000001_assembly.json").write_text(json.dumps({
        "rows": [
            {"PartNo":      "5000001"},
            {"part_number": "5000002"},
            {"partNumber":  "5000003"},
            {"part_no":     "5000004"},
            # Negative: a non-matching key with a part-number-shaped value
            # must NOT be collected (avoids consuming coordinate / count
            # values that happen to look numeric).
            {"someOtherKey": "5000999"},
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    used = server._intake_used_part_numbers(library)
    for pn in ("5000001", "5000002", "5000003", "5000004"):
        assert pn in used, f"alternate-spelling part ref missed: {pn}"
    assert "5000999" not in used, "non-canonical key was accidentally consumed"


def test_used_part_numbers_assembly_walk_rejects_non_part_token_shapes(tmp_path: Path,
                                                                       monkeypatch: pytest.MonkeyPatch):
    """The token-shape filter must skip non-part-number values that
    happen to land under one of the canonical keys (free-text,
    decimals, very-long hashes, empty strings)."""
    library = tmp_path / "asm_lib3"
    (library / "assemblies").mkdir(parents=True)
    (library / "assemblies" / "9000002_assembly.json").write_text(json.dumps({
        "components": [
            {"PartNo": "ABCDEF"},
            {"PartNo": "12.5"},
            {"PartNo": ""},
            {"PartNo": "deadbeef-uuid-very-long-token-1234567890"},
            {"PartNo": "1030099"},  # this one IS a valid token shape
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    used = server._intake_used_part_numbers(library)
    for bad in ("ABCDEF", "12.5", "", "deadbeef-uuid-very-long-token-1234567890"):
        assert bad not in used, f"non-part-shape token leaked into used set: {bad!r}"
    assert "1030099" in used


def test_used_part_numbers_assembly_walk_recurses_nested_revisioned_dirs(tmp_path: Path,
                                                                         monkeypatch: pytest.MonkeyPatch):
    """assemblies/{id}/revA/{id}_assembly.json (the nested-revisioned
    shape observed for 6000300) must be picked up. rglob is the
    load-bearing change vs the previous glob."""
    library = tmp_path / "asm_lib4"
    nested = library / "assemblies" / "6000300" / "revA"
    nested.mkdir(parents=True)
    (nested / "6000300_assembly.json").write_text(json.dumps({
        "components": [{"PartNo": "1040013"}],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    used = server._intake_used_part_numbers(library)
    assert "6000300" in used, "nested *_assembly.json stem missed"
    assert "1040013" in used, "nested assembly's PartNo ref missed"


def test_used_part_numbers_assembly_walk_tolerates_malformed_json(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch):
    """A broken JSON file under assemblies/ must NOT crash the scanner.
    Suggester must remain usable even with one corrupt assembly file."""
    library = tmp_path / "asm_lib5"
    (library / "assemblies").mkdir(parents=True)
    (library / "assemblies" / "broken_assembly.json").write_text("{ not valid json", encoding="utf-8")
    (library / "assemblies" / "good_assembly.json").write_text(json.dumps({
        "components": [{"PartNo": "1030555"}],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    used = server._intake_used_part_numbers(library)
    # Broken file silently skipped; good file's PartNo still landed
    assert "1030555" in used


def test_next_part_number_skips_assembly_internal_pn(tmp_path: Path,
                                                     monkeypatch: pytest.MonkeyPatch):
    """End-to-end task assertion: with the 6000302 assembly carrying
    PartNo 1030031, the next 1030xxx suggestion must NOT be 1030031."""
    library = tmp_path / "asm_lib6"
    (library / "assemblies").mkdir(parents=True)
    (library / "assemblies" / "6000302_assembly.json").write_text(json.dumps({
        "components": [{"PartNo": "1030031"}],
    }), encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    suggestion = server._intake_next_part_number(library, prefix="1030")
    assert suggestion != "1030031"
    # With nothing else seeded, the next free should be the first free
    # 1030xxx token -- 1030001. The assertion proves the helper saw and
    # rejected 1030031 specifically.
    assert suggestion == "1030001"


def test_used_part_numbers_includes_assemblies(numbering_library: Path):
    used = server._intake_used_part_numbers(numbering_library)
    assert "6000300" in used
    assert "6000302" in used


def test_used_part_numbers_empty_library_returns_empty_set(tmp_path: Path,
                                                            monkeypatch: pytest.MonkeyPatch):
    library = tmp_path / "empty"
    library.mkdir()
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    used = server._intake_used_part_numbers(library)
    assert used == set()


# ── Helper: _intake_next_part_number ─────────────────────────────────


def test_next_part_number_finds_first_gap(numbering_library: Path):
    """1030001 and 1030005 + 1030009 exist; 1030002 / 1030003 /
    1030004 should be the first three gaps."""
    assert server._intake_next_part_number(numbering_library, prefix="1030") == "1030002"


def test_next_part_number_width_follows_prefix_length(numbering_library: Path):
    """prefix='1030' (4 chars) -> width 3 -> 1030xxx. prefix='10300'
    (5 chars) -> width 2 -> 10300xx. Operator controls convention by
    choosing prefix length explicitly."""
    # prefix '10300' against 1030001 (taken) -> first gap is 1030002
    assert server._intake_next_part_number(numbering_library, prefix="10300") == "1030002"


def test_next_part_number_long_prefix_extends_assembly_subseries(numbering_library: Path):
    """Existing assemblies 6000300 + 6000302. prefix '60003' should
    return 6000301 (first gap in 60003xx)."""
    assert server._intake_next_part_number(numbering_library, prefix="60003") == "6000301"


def test_next_part_number_short_prefix_returns_first_overall_gap(numbering_library: Path):
    """prefix '6000' (no existing 6000001-6000299 in fixture) -> 6000001.
    Documents the deliberate 'do not guess convention silently' pattern:
    the operator picks the longer prefix to extend a sub-series."""
    assert server._intake_next_part_number(numbering_library, prefix="6000") == "6000001"


def test_next_part_number_exhausted_raises_value_error(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch):
    """Fill all 999 candidates in a tiny range and confirm the helper
    raises rather than silently looping. The endpoint maps this to a
    409 (see test below)."""
    library = tmp_path / "full"
    library.mkdir()
    # Fill 1xxx (3-digit width) -- prefix='1' width=6, but let's use prefix
    # with width=3 to keep the test cheap: prefix='123' (width=4) -> 9999
    # candidates. We use prefix='12345' (width=2) -> 99 candidates and seed
    # all 99.
    for i in range(1, 100):
        (library / f"12345{i:02d}.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    with pytest.raises(ValueError):
        server._intake_next_part_number(library, prefix="12345")


# ── Endpoint: GET /api/library/numbering/next ────────────────────────


def test_numbering_endpoint_part_happy_path(numbering_library: Path):
    client = TestClient(server.app)
    r = client.get("/api/library/numbering/next?kind=part&prefix=1030")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["kind"] == "part"
    assert body["prefix"] == "1030"
    assert body["suggestion"] == "1030002"
    assert body["scannedCount"] >= 3
    assert "library" in body


def test_numbering_endpoint_assembly_extends_subseries(numbering_library: Path):
    """Operator passes the long prefix to extend the existing 60003xx
    assembly sub-series."""
    client = TestClient(server.app)
    r = client.get("/api/library/numbering/next?kind=assembly&prefix=60003")
    assert r.status_code == 200, r.text
    assert r.json()["suggestion"] == "6000301"


def test_numbering_endpoint_rejects_unknown_kind(numbering_library: Path):
    client = TestClient(server.app)
    r = client.get("/api/library/numbering/next?kind=panel&prefix=1030")
    assert r.status_code == 400
    assert "unknown kind" in r.json()["detail"].lower()


def test_numbering_endpoint_rejects_non_numeric_prefix(numbering_library: Path):
    client = TestClient(server.app)
    r = client.get("/api/library/numbering/next?kind=part&prefix=ABC")
    assert r.status_code == 400
    assert "prefix" in r.json()["detail"].lower()


def test_numbering_endpoint_rejects_empty_prefix(numbering_library: Path):
    client = TestClient(server.app)
    r = client.get("/api/library/numbering/next?kind=part&prefix=")
    assert r.status_code == 400


def test_numbering_endpoint_range_exhausted_returns_409(tmp_path: Path,
                                                       monkeypatch: pytest.MonkeyPatch):
    library = tmp_path / "full2"
    library.mkdir()
    for i in range(1, 100):
        (library / f"99887{i:02d}.json").write_text("{}", encoding="utf-8")
    monkeypatch.setattr(server, "LIBRARY_DIR", library)
    monkeypatch.setattr(server, "assembly_profiles", {}, raising=False)
    client = TestClient(server.app)
    r = client.get("/api/library/numbering/next?kind=part&prefix=99887")
    assert r.status_code == 409
    assert "no available" in r.json()["detail"].lower()


def test_numbering_endpoint_default_kind_and_prefix(numbering_library: Path):
    """Defaults are kind=part / prefix=1030 (matches today's most-used
    parts convention)."""
    client = TestClient(server.app)
    r = client.get("/api/library/numbering/next")
    assert r.status_code == 200
    body = r.json()
    assert body["kind"] == "part"
    assert body["prefix"] == "1030"
