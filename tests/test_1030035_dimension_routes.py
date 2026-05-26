"""Routing audit for 1030035 Rev A (air-ride caster).

Locks the spec's six demo handoff phrases against the actual
semantic_regions + sketch_dimension_intent_map maps on disk.
Specifically guards the wheel-vs-swivel ambiguity that motivated
this audit: "wheel diameter" MUST route to RevolveTireTread /
SketchTireTreadProfile / TreadOD and NEVER to the swivel-profile
sketch (RevolveCasterWheelAndSwivelProfile / SketchCasterWheelAndSwivelProfile).

If any of these routes change unintentionally, this test catches
it before the next demo handoff goes to SolidWorks.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import server  # noqa: E402
from ai_inspector.sketch_intent import lookup_sketch_dimension_intent


PN = "1030035"
REV = "revA"


# The library file the audit operates on. We do NOT monkeypatch the
# library here -- the whole point is to test the REAL on-disk data.
@pytest.fixture(scope="module")
def real_library() -> Path:
    p = server.library_path()
    # Only run when the real fixture is present; CI environments
    # without the 400S library skip cleanly.
    if not (p / "parts" / PN / REV / f"{PN}_sketch_dimension_intent_map.json").exists():
        pytest.skip(f"1030035 Rev A maps not present at {p}; audit test is repo-local")
    return p


def _resolve_first_cad_feature_id(library: Path, phrase: str) -> str | None:
    """Resolve a phrase to the first cadFeatureId via the same
    resolver Sage uses for handoff prep. Returns None when the
    phrase doesn't match any region."""
    hits = server._semantic_resolve_phrases(library, PN, REV, [phrase])
    if not hits:
        return None
    first = hits[0]
    cad_ids = list(first.cadFeatureIds or [])
    return cad_ids[0] if cad_ids else None


def _expect_route(
    library: Path,
    phrase:           str,
    expected_cad:     str,
    expected_sketch:  str,
    expected_short:   str,
) -> None:
    cad = _resolve_first_cad_feature_id(library, phrase)
    assert cad == expected_cad, (
        f"phrase {phrase!r} resolved to cadFeatureId {cad!r}; "
        f"expected {expected_cad!r}"
    )
    entry = lookup_sketch_dimension_intent(library, PN, REV, cad, instruction=phrase)
    assert entry is not None, (
        f"phrase {phrase!r} found cadFeatureId {cad!r} but no sketch "
        f"intent entry matched the phrase"
    )
    assert entry.get("sketchFeature") == expected_sketch, (
        f"phrase {phrase!r} routed to sketch {entry.get('sketchFeature')!r}; "
        f"expected {expected_sketch!r}"
    )
    assert entry.get("dimensionShortName") == expected_short, (
        f"phrase {phrase!r} routed to dim {entry.get('dimensionShortName')!r}; "
        f"expected {expected_short!r}"
    )


# ── Spec-required happy paths ─────────────────────────────────────

def test_wheel_diameter_routes_to_tread_not_swivel(real_library: Path):
    """REGRESSION GUARD for the bug that motivated this audit. Operator
    asks for wheel diameter -> must hit RevolveTireTread and NEVER the
    shared swivel-profile sketch."""
    _expect_route(
        real_library,
        phrase="set wheel diameter to 90 mm",
        expected_cad="revolution_revolvetiretread",
        expected_sketch="SketchTireTreadProfile",
        expected_short="TreadOD",
    )


def test_swivel_outside_diameter_routes_to_swivel_profile(real_library: Path):
    _expect_route(
        real_library,
        phrase="set swivel outside diameter to 95 mm",
        expected_cad="revolution_revolvecasterwheelandswivelprofile",
        expected_sketch="SketchCasterWheelAndSwivelProfile",
        expected_short="SwivelOD",
    )


def test_mounting_plate_width_routes_to_mounting_plate_overall_size(real_library: Path):
    _expect_route(
        real_library,
        phrase="set mounting plate width to 110 mm",
        expected_cad="extrusion_boss_mountingplate",
        expected_sketch="Sketch_MountingPlate_OverallSize",
        expected_short="PlateWidth",
    )


def test_mounting_slot_width_routes_to_mount_plate_slots(real_library: Path):
    _expect_route(
        real_library,
        phrase="set mounting slot width to 10 mm",
        expected_cad="ice_cutmountplateslots",
        expected_sketch="SketchMountPlateSlots",
        expected_short="SlotWidth",
    )


def test_stud_diameter_routes_to_hub_studs(real_library: Path):
    _expect_route(
        real_library,
        phrase="set stud diameter to 16 mm",
        expected_cad="ice_bosshubstuds",
        expected_sketch="SketchHubStuds",
        expected_short="StudDiameter",
    )


def test_bolt_head_diameter_routes_to_hub_bolt_heads(real_library: Path):
    _expect_route(
        real_library,
        phrase="set bolt head diameter to 15 mm",
        expected_cad="ice_bosshubboltheads",
        expected_sketch="SketchHubBoltHeads",
        expected_short="BoltHeadDiameter",
    )


# ── Negative guards ───────────────────────────────────────────────

def test_wheel_diameter_never_resolves_to_swivel_profile_sketch(real_library: Path):
    """Direct negative: no matter what wheel phrasing the operator
    uses, the sketch_intent lookup against the SWIVEL feature must
    NOT return a hit (the rogue WheelOD entry was removed during
    audit)."""
    swivel_cad = "revolution_revolvecasterwheelandswivelprofile"
    for phrase in (
        "set wheel diameter to 90 mm",
        "set tire diameter to 90 mm",
        "set wheel outside diameter to 90 mm",
        "set caster wheel diameter to 90 mm",
    ):
        entry = lookup_sketch_dimension_intent(real_library, PN, REV, swivel_cad, instruction=phrase)
        assert entry is None or entry.get("dimensionShortName") != "WheelOD", (
            f"phrase {phrase!r} resolved against swivel cadFeatureId returned "
            f"entry {entry!r}; the unsafe WheelOD route must stay removed"
        )


def test_semantic_regions_cad_features_all_exist_in_feature_colors(real_library: Path):
    """Data integrity: every cadFeatureId referenced by a semantic
    region must exist in feature_colors.json so the highlight pipeline
    has something to colour."""
    import json
    sr = json.loads((real_library / "parts" / PN / REV / f"{PN}_semantic_regions.json").read_text(encoding="utf-8-sig"))
    fc = json.loads((real_library / "parts" / PN / REV / f"{PN}_feature_colors.json").read_text(encoding="utf-8-sig"))
    fc_ids = {f["cad_feature_id"] for f in fc.get("features") or []}
    missing = []
    for r in sr.get("regions") or []:
        cads = (r.get("cadTargets") or {}).get("cadFeatureIds") or []
        for c in cads:
            if c not in fc_ids:
                missing.append((r.get("regionId"), c))
    assert not missing, f"semantic regions reference cadFeatureIds not in feature_colors: {missing}"


def test_sketch_intent_cad_features_all_have_a_region(real_library: Path):
    """Data integrity: every sketch_intent entry's cadFeatureId must
    appear in at least one semantic region so the handoff path can
    resolve a region from the sketch (used by lookup gate)."""
    import json
    sr = json.loads((real_library / "parts" / PN / REV / f"{PN}_semantic_regions.json").read_text(encoding="utf-8-sig"))
    si = json.loads((real_library / "parts" / PN / REV / f"{PN}_sketch_dimension_intent_map.json").read_text(encoding="utf-8-sig"))
    region_cad_ids = set()
    for r in sr.get("regions") or []:
        for c in (r.get("cadTargets") or {}).get("cadFeatureIds") or []:
            region_cad_ids.add(c)
    orphans = []
    for e in si.get("dimensions") or []:
        cad = e.get("cadFeatureId")
        if cad and cad not in region_cad_ids:
            orphans.append((e.get("dimensionShortName"), cad))
    assert not orphans, f"sketch_intent entries with no region: {orphans}"
