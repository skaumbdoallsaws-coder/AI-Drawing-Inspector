"""No-contact regions (P3 constraint gate) and design-hash stability for the new constraint fields.

All data is synthetic TEST data. No carrier, customer address or CAD file is involved.
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_inspector.codex_runtime.packaging_tools import Preservation
from ai_inspector.packaging_shipping.comparison import integrity
from ai_inspector.packaging_shipping.geometry import FACES, assess, digest, envelope, no_contact_zone, oriented, product_axes
from ai_inspector.packaging_shipping.models import Carton, Design
from ai_inspector.packaging_shipping.packing import propose

PRODUCT = {"name": "TEST product", "dimensions_m": [0.1, 0.08, 0.04], "mass_kg": 0.5,
           "mass_basis": "user_measured", "mass_evidence": "TEST scale"}
CARTON = {"name": "TEST carton", "inner_m": [0.17, 0.23, 0.12], "outer_m": [0.2032, 0.254, 0.1524], "tare_kg": 0.1,
          "tare_evidence": "TEST scale", "max_payload_kg": 5, "cost_usd": 1.5}
LEGACY = {"name": "TEST hash", "quantity": 1, "product": PRODUCT, "constraints": {"contents": "ordinary_nonhazardous"},
          "packages": [{"id": "box_0", "carton": CARTON, "allowance_kg": 0.05, "allowance_evidence": "TEST tape",
                        "placements": [{"id": "item_0", "position_m": [0.02, 0.02, 0.02]}]}]}
# digest() of LEGACY computed with the code at 4c37436, before cushion, package_allowance and no_contact existed.
LEGACY_HASH = "3e4286363422126e239a0790fde307ad20f8d02ad39a1b1058b01f53731c2e73"
# (carton axis, mirrored) per product axis for each dimension order; the same table is asserted against
# orientationRows() in tests/packaging_ui.test.cjs, so the check and the viewer agree on which face is where.
FACE_MAPPING = [((0, False), (1, False), (2, False)), ((1, False), (0, True), (2, False)), ((2, False), (0, False), (1, False)),
                ((2, False), (1, False), (0, True)), ((1, False), (2, False), (0, False)), ((0, True), (2, False), (1, False))]


def region(face="y_max", gap=0.005, area=None, rid="nc_1"):
    return {"id": rid, "name": "TEST lens", "face": face, "area": area, "air_gap_m": gap, "evidence": "TEST polished face"}


def block(iid, lower, upper, pockets=()):
    return {"id": iid, "name": "TEST foam", "dimensions_m": [round(u - l, 9) for l, u in zip(lower, upper)],
            "position_m": list(lower), "density_kg_m3": 35.0, "material_evidence": "TEST supplier density",
            "pockets": list(pockets)}


def design(regions=(), placements=None, inserts=(), orientations=(0,), carton=CARTON):
    placements = placements or [{"id": "item_0", "position_m": [0.02, 0.02, 0.02]}]
    return Design.model_validate({
        "name": "TEST no-contact", "quantity": len(placements), "product": PRODUCT,
        "constraints": {"contents": "ordinary_nonhazardous", "allowed_orientations": list(orientations), "no_contact": list(regions)},
        "packages": [{"id": "box_0", "carton": carton, "allowance_kg": 0.05, "allowance_evidence": "TEST tape",
                      "placements": placements, "inserts": list(inserts)}]})


def findings(d, code):
    return [f for f in assess(d)["findings"] if f["code"] == code]


def test_designs_without_the_new_constraints_keep_their_earlier_hash():
    legacy = Design.model_validate(LEGACY)
    assert digest(legacy) == LEGACY_HASH
    assert not {"cushion", "package_allowance", "no_contact"} & set(legacy.model_dump(mode="json")["constraints"])
    explicit = Design.model_validate(LEGACY | {"constraints": LEGACY["constraints"] | {
        "cushion": None, "package_allowance": None, "no_contact": []}})
    assert explicit == legacy and digest(explicit) == LEGACY_HASH
    marked = Design.model_validate(LEGACY | {"constraints": LEGACY["constraints"] | {"no_contact": [region()]}})
    assert digest(marked) != LEGACY_HASH
    assert Design.model_validate_json(marked.model_dump_json()) == marked
    assert marked.model_dump(mode="json")["constraints"]["no_contact"] == [region()]


def test_regions_are_closed_and_documented():
    for bad in (region() | {"evidence": "  "}, region() | {"air_gap_m": 0.0}, region() | {"face": "top"},
                region() | {"area": {"u_m": [0.03, 0.01], "v_m": [0.0, 0.02]}}, region() | {"note": "x"}):
        with pytest.raises(ValidationError):
            design([bad])
    with pytest.raises(ValidationError, match="unique"):
        design([region(), region(face="x_min")])
    with pytest.raises(ValidationError):
        design([region(rid=f"nc_{i}") for i in range(13)])


def test_face_mapping_matches_the_viewer_rotation():
    assert [product_axes(o) for o in range(6)] == FACE_MAPPING
    for o in range(6):
        assert sorted(axis for axis, _ in product_axes(o)) == [0, 1, 2]
        assert sum(mirrored for _, mirrored in product_axes(o)) == (o in (1, 3, 5))


def test_clear_regions_pass_and_material_walls_or_products_in_the_gap_fail():
    above = lambda y: block("pad_top", (0, y, 0), (0.17, 0.2, 0.12))
    clear = design([region()])
    assert not findings(clear, "no_contact_violated") and assess(clear)["rate_ready"]
    assert assess(clear)["no_contact"] == [{"package_id": "box_0", "region_id": "nc_1", "products": 1, "touching": 0, "facing_down": 0}]
    touching = design([region()], inserts=[above(0.103)])
    [finding] = findings(touching, "no_contact_violated")
    assert finding["entity_ids"] == ["item_0", "nc_1"] and "5.0 mm" in finding["message"]
    assert not assess(touching)["rate_ready"]
    assert not findings(design([region()], inserts=[above(0.105)]), "no_contact_violated"), "exactly the air gap is clear"
    assert findings(design([region("x_max", 0.06)]), "no_contact_violated"), "carton wall inside the gap"
    assert not findings(design([region("x_max", 0.05)]), "no_contact_violated")
    deep = CARTON | {"inner_m": [0.17, 0.23, 0.2], "outer_m": [0.2032, 0.254, 0.23]}
    pair = [{"id": "item_0", "position_m": [0.02, 0.02, 0.02]}, {"id": "item_1", "position_m": [0.02, 0.02, 0.07]}]
    [finding] = findings(design([region("z_max", 0.015)], pair, carton=deep), "no_contact_violated")
    assert finding["entity_ids"] == ["item_0", "nc_1"] and "for 1 of 2 products" in finding["message"]
    assert not findings(design([region("z_max", 0.009)], pair, carton=deep), "no_contact_violated")


def test_partial_areas_and_pocket_voids():
    right = block("pad_right", (0.08, 0.101, 0), (0.17, 0.2, 0.12))
    left_half = {"u_m": [0.0, 0.05], "v_m": [0.0, 0.04]}
    right_half = {"u_m": [0.05, 0.1], "v_m": [0.0, 0.04]}
    assert not findings(design([region(area=left_half)], inserts=[right]), "no_contact_violated")
    assert findings(design([region(area=right_half)], inserts=[right]), "no_contact_violated")
    [outside] = findings(design([region(area={"u_m": [0.0, 0.11], "v_m": [0.0, 0.04]})]), "no_contact_area_outside")
    assert outside["entity_ids"] == ["nc_1"] and outside["severity"] == "error"
    pocket = {"id": "pocket_1", "dimensions_m": [0.11, 0.1, 0.05], "position_m": [0.015, 0.02, 0.015]}
    cradle = block("cradle", (0, 0, 0), (0.17, 0.12, 0.12), [pocket])
    assert not {f["code"] for f in assess(design([], inserts=[cradle]))["findings"]} & {"insert_overlap", "pocket_wall_thin", "pocket_not_top_open"}
    assert not findings(design([region("x_max", 0.004)], inserts=[cradle]), "no_contact_violated"), "air inside the pocket"
    assert findings(design([region("x_max", 0.006)], inserts=[cradle]), "no_contact_violated"), "pocket wall inside the gap"


def test_rotated_products_check_the_face_the_viewer_shows():
    rotated = [{"id": "item_0", "position_m": [0.04, 0.02, 0.02], "orientation": 1}]
    low_x = block("pad_low_x", (0, 0, 0), (0.035, 0.2, 0.12))
    high_x = block("pad_high_x", (0.125, 0, 0), (0.17, 0.2, 0.12))
    box = envelope((0.04, 0.02, 0.02), oriented(PRODUCT["dimensions_m"], 1))
    zone, axis, toward_max = no_contact_zone(box, PRODUCT["dimensions_m"], 1, design([region("y_max", 0.01)]).constraints.no_contact[0])
    assert (axis, toward_max) == (0, False) and zone[0][0] == pytest.approx(0.03)
    # Product +Y faces carton -X in this rotation, so only the low-X pad is inside its gap.
    assert findings(design([region("y_max", 0.01)], rotated, [low_x], orientations=(1,)), "no_contact_violated")
    assert not findings(design([region("y_max", 0.01)], rotated, [high_x], orientations=(1,)), "no_contact_violated")
    assert findings(design([region("y_min", 0.01)], rotated, [high_x], orientations=(1,)), "no_contact_violated")


def test_a_region_facing_the_floor_needs_review():
    [warning] = findings(design([region("y_min", 0.005)]), "no_contact_faces_down")
    assert warning["severity"] == "warning" and warning["entity_ids"] == ["box_0", "nc_1"]
    assert not findings(design([region("y_min", 0.005)]), "no_contact_violated")
    assert not findings(design([region("y_max", 0.005)]), "no_contact_faces_down")


def independent_clearance(candidate, gap_by_face):
    """Least distance from each regioned face to a wall or another product, from FACE_MAPPING, not geometry.py."""
    least = {}
    for package in candidate.packages:
        boxes = [(item, envelope(item.position_m, oriented(candidate.product.dimensions_m, item.orientation))) for item in package.placements]
        for item, (lo, hi) in boxes:
            for face in gap_by_face:
                axis_p, outward = FACES[face]
                i, mirrored = FACE_MAPPING[item.orientation][axis_p]
                up = outward != mirrored
                distance = package.carton.inner_m[i] - hi[i] if up else lo[i]
                for other, (olo, ohi) in boxes:
                    lateral = all(min(hi[k], ohi[k]) - max(lo[k], olo[k]) > 1e-9 for k in range(3) if k != i)
                    if other.id != item.id and lateral:
                        gap = olo[i] - hi[i] if up else lo[i] - ohi[i]
                        if gap >= -1e-9:
                            distance = min(distance, gap)
                least[face] = min(least.get(face, 1.0), distance)
    return least


def test_proposals_keep_the_air_gap_clear():
    gaps = {"x_max": 0.01, "y_max": 0.005}
    base = design([region(face, gap, rid=f"nc_{i}") for i, (face, gap) in enumerate(gaps.items())],
                  [{"id": f"item_{i}", "position_m": [0.02, 0.02, 0.02]} for i in range(6)], orientations=(0, 1))
    cartons = [Carton.model_validate(CARTON | {"name": "TEST wide", "inner_m": [0.4, 0.2, 0.3], "outer_m": [0.41, 0.21, 0.31]})]
    result = propose(base, cartons)
    assert result["candidates"] and result["preservation"]["no_contact"] == "air_gap_reserved"
    assert "No-contact air gaps are kept clear" in result["notice"]
    Preservation.model_validate(result["preservation"])
    for candidate in result["candidates"]:
        rebuilt = Design.model_validate(candidate["design"])
        assert rebuilt.constraints.no_contact == base.constraints.no_contact
        assert not {f["code"] for f in assess(rebuilt)["findings"]} & {"no_contact_violated", "no_contact_area_outside"}
        least = independent_clearance(rebuilt, gaps)
        assert all(least[face] >= gap - 1e-9 for face, gap in gaps.items()), least
    plain = propose(design([], [{"id": f"item_{i}", "position_m": [0.02, 0.02, 0.02]} for i in range(6)], orientations=(0, 1)), cartons)
    assert plain["preservation"]["no_contact"] == "not_required"
    Preservation.model_validate(plain["preservation"])


def test_a_carton_that_only_fits_without_the_gap_is_not_proposed():
    tight = Carton.model_validate(CARTON | {"name": "TEST tight", "inner_m": [0.115, 0.095, 0.055], "outer_m": [0.125, 0.105, 0.065]})
    loose = Design.model_validate(design().model_dump() | {"constraints": {"clearance_m": 0.005, "gap_m": 0.005,
                                                                          "contents": "ordinary_nonhazardous"}})
    assert propose(loose, [tight])["candidates"]
    guarded = Design.model_validate(loose.model_dump() | {"constraints": loose.constraints.model_dump() | {"no_contact": [region("x_max", 0.01)]}})
    result = propose(guarded, [tight])
    assert not result["candidates"] and result["rejected"][0]["reason"] == "does_not_fit"


def test_comparison_treats_changed_regions_as_changed_constraints():
    baseline, guarded = design(), design([region()])
    reasons = integrity({"design": baseline, "assessment": assess(baseline)}, {"design": guarded, "assessment": assess(guarded)})
    assert "constraints_changed" in reasons
    assert integrity({"design": guarded, "assessment": assess(guarded)}, {"design": guarded, "assessment": assess(guarded)}) == []
