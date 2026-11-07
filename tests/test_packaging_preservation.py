"""Proposals keep protection and packing mass (P3 preservation gate).

All data here is synthetic TEST data or the sourced catalog records; no customer CAD,
addresses or carrier access is involved.
"""
from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from ai_inspector.packaging_shipping.catalog import catalog
from ai_inspector.packaging_shipping.components import foam_along
from ai_inspector.packaging_shipping.geometry import assess
from ai_inspector.packaging_shipping.models import Carton, Design, Insert, MaterialDensity
from ai_inspector.packaging_shipping.packing import lining, propose
from ai_inspector.packaging_shipping.service import PackagingError

FOAM = {"name": "TEST foam", "density_kg_m3": 35.0, "evidence": "TEST supplier density"}
CUSHION = {"floor_m": 0.02, "top_m": 0.02, "sides_m": 0.015, "material": FOAM, "evidence": "TEST drop requirement"}


def carton_data(inner=(0.4, 0.2, 0.3), payload=10.0):
    return {"name": "TEST carton", "inner_m": list(inner), "outer_m": [x + 0.01 for x in inner],
            "tare_kg": 0.3, "tare_evidence": "TEST scale", "max_payload_kg": payload, "cost_usd": 1.0}


def design_data(quantity=6, cushion=CUSHION, inserts=True, allowance=(0.05, "TEST tape")):
    package = {"id": "box_1", "carton": carton_data(), "placements": [],
               "allowance_kg": allowance[0], "allowance_evidence": allowance[1]}
    if inserts:
        package["inserts"] = [{"id": "pad_1", "name": "TEST pad", "dimensions_m": [0.4, 0.02, 0.3],
                               "position_m": [0, 0, 0], "density_kg_m3": 35.0, "material_evidence": "TEST"}]
    return {"name": "TEST", "quantity": quantity,
            "product": {"name": "TEST product", "dimensions_m": [0.1, 0.06, 0.04], "mass_kg": 0.4,
                        "mass_basis": "user_measured", "mass_evidence": "TEST scale"},
            "constraints": {"clearance_m": 0.005, "gap_m": 0.005, "allowed_orientations": [0, 1],
                            "contents": "ordinary_nonhazardous", "cushion": cushion},
            "packages": [package]}


def codes(assessment, severity=None):
    return {f["code"] for f in assessment["findings"] if severity is None or f["severity"] == severity}


def independent_gross(design):
    """Gross mass recomputed from the records, not from assess()."""
    total = 0.0
    for package in design.packages:
        pads = sum(math.prod(i.dimensions_m) * i.density_kg_m3 for i in package.inserts)
        total += len(package.placements) * design.product.mass_kg + pads + package.carton.tare_kg + package.allowance_kg
    return total


def test_cushion_and_allowance_rules_are_closed_and_documented():
    with pytest.raises(ValidationError):
        Design.model_validate(design_data(cushion=CUSHION | {"floor_m": 0.0, "top_m": 0.0, "sides_m": 0.0}))
    with pytest.raises(ValidationError):
        Design.model_validate(design_data(cushion=CUSHION | {"evidence": "   "}))
    with pytest.raises(ValidationError):
        Design.model_validate(design_data(cushion=CUSHION | {"extra": 1}))
    with pytest.raises(ValidationError):
        Design.model_validate(design_data(cushion=CUSHION | {"sides_m": 0.3}))
    data = design_data()
    data["constraints"]["package_allowance"] = {"allowance_kg": 0.1, "evidence": " "}
    with pytest.raises(ValidationError):
        Design.model_validate(data)
    plain = Design.model_validate(design_data(cushion=None))
    assert plain.constraints.cushion is None and plain.constraints.package_allowance is None


def test_proposal_refuses_to_drop_inserts_without_a_cushion_requirement():
    design = Design.model_validate(design_data(cushion=None))
    before = design.model_dump()
    with pytest.raises(PackagingError) as caught:
        propose(design, [Carton.model_validate(carton_data())])
    assert caught.value.code == "protection_requirement_needed" and caught.value.status == 409
    assert design.model_dump() == before
    bare = Design.model_validate(design_data(cushion=None, inserts=False))
    result = propose(bare, [Carton.model_validate(carton_data())])
    assert result["candidates"] and result["preservation"]["cushion"] == "not_required"


@pytest.mark.parametrize("quantity", [1, 6])
def test_candidates_rebuild_the_lining_and_keep_every_mass_term(quantity):
    design = Design.model_validate(design_data(quantity=quantity))
    result = propose(design, [Carton.model_validate(carton_data())], max_packages=3)
    assert result["preservation"] == {"cushion": "rebuilt_from_requirement", "allowance": "carried_forward",
                                      "carton_graphics": "none", "insert_graphics_dropped": 0, "no_contact": "not_required"}
    assert result["candidates"]
    for candidate in result["candidates"]:
        packed = Design.model_validate(candidate["design"])
        assessment = candidate["assessment"]
        assert assessment == assess(packed)
        assert not codes(assessment, "error"), assessment["findings"]
        assert sum(len(p.placements) for p in packed.packages) == quantity
        for package in packed.packages:
            assert {i.id for i in package.inserts} == {"cushion-floor", "cushion-top", "cushion-x-min",
                                                       "cushion-x-max", "cushion-z-min", "cushion-z-max"}
            assert package.allowance_kg == 0.05 and package.allowance_evidence == "TEST tape"
        rows = assessment["cushion"]
        assert all(r["verified"] and r["floor_m"] >= 0.02 - 1e-9 and r["top_m"] >= 0.02 - 1e-9
                   and r["sides_m"] >= 0.015 - 1e-9 for r in rows)
        assert assessment["total_gross_kg"] == pytest.approx(independent_gross(packed))
        lining_kg = sum(math.prod(i.dimensions_m) * i.density_kg_m3 for p in packed.packages for i in p.inserts)
        assert lining_kg > 0
        assert assessment["total_gross_kg"] >= quantity * 0.4 + len(packed.packages) * (0.3 + 0.05) + lining_kg - 1e-9


def test_a_candidate_cannot_become_lighter_or_rate_ready_by_losing_protection_or_allowance():
    design = Design.model_validate(design_data())
    candidate = Design.model_validate(propose(design, [Carton.model_validate(carton_data())])["candidates"][0]["design"])
    assert assess(candidate)["rate_ready"]
    for pad in ("cushion-floor", "cushion-top", "cushion-x-max", "cushion-z-min"):
        stripped = candidate.model_copy(deep=True)
        for package in stripped.packages:
            package.inserts = [i for i in package.inserts if i.id != pad]
        result = assess(stripped)
        assert "cushion_insufficient" in codes(result, "error") and not result["rate_ready"], pad
    thinner = candidate.model_copy(deep=True)
    for package in thinner.packages:
        floor = next(i for i in package.inserts if i.id == "cushion-floor")
        floor.dimensions_m = (floor.dimensions_m[0], 0.01, floor.dimensions_m[2])
    result = assess(thinner)
    assert "cushion_insufficient" in codes(result, "error")
    assert "floor 10.0 of 20.0 mm" in next(f["message"] for f in result["findings"] if f["code"] == "cushion_insufficient")
    no_allowance = candidate.model_copy(deep=True)
    for package in no_allowance.packages:
        package.allowance_kg, package.allowance_evidence = None, ""
    result = assess(no_allowance)
    assert "allowance_unknown" in codes(result, "error") and result["total_gross_kg"] is None and not result["rate_ready"]


def test_allowance_rule_wins_and_disagreeing_saved_allowances_stay_unknown():
    data = design_data()
    data["packages"].append({**data["packages"][0], "id": "box_2", "inserts": [], "allowance_kg": 0.2,
                             "allowance_evidence": "TEST heavier tape"})
    disagree = Design.model_validate(data)
    result = propose(disagree, [Carton.model_validate(carton_data())])
    assert result["preservation"]["allowance"] == "unknown"
    for candidate in result["candidates"]:
        assert "allowance_unknown" in codes(candidate["assessment"], "error")
        assert candidate["assessment"]["total_gross_kg"] is None and not candidate["assessment"]["rate_ready"]
    data["constraints"]["package_allowance"] = {"allowance_kg": 0.12, "evidence": "TEST tape and labels per carton"}
    ruled = propose(Design.model_validate(data), [Carton.model_validate(carton_data())])
    assert ruled["preservation"]["allowance"] == "rule"
    packages = [p for c in ruled["candidates"] for p in c["design"]["packages"]]
    assert packages and all(p["allowance_kg"] == 0.12 and p["allowance_evidence"] == "TEST tape and labels per carton"
                            for p in packages)


def test_shared_carton_graphics_are_carried_and_insert_graphics_are_reported():
    data = design_data()
    data["packages"][0]["graphics"] = [{"id": "label_1", "text": "TEST FRAGILE"},
                                       {"id": "pad_mark", "target": "insert", "target_id": "pad_1", "text": "TEST"}]
    result = propose(Design.model_validate(data), [Carton.model_validate(carton_data())])
    assert result["preservation"]["carton_graphics"] == "carried_forward"
    assert result["preservation"]["insert_graphics_dropped"] == 1
    for candidate in result["candidates"]:
        for package in candidate["design"]["packages"]:
            assert [g["id"] for g in package["graphics"]] == ["label_1"]


def test_lining_that_leaves_no_cavity_is_rejected_not_scaled():
    tiny = Carton.model_validate(carton_data(inner=(0.05, 0.04, 0.05)))
    assert lining(tiny, Design.model_validate(design_data()).constraints.cushion) is None
    result = propose(Design.model_validate(design_data()), [tiny])
    assert result["candidates"] == []
    assert result["rejected"] == [{"carton": "TEST carton", "reason": "lining_leaves_no_cavity"}]


def test_payload_capacity_counts_the_lining_and_allowance():
    # Six products weigh 2.4 kg. With 0.05 kg allowance and the lining the contents exceed 2.5 kg.
    carton = Carton.model_validate(carton_data(payload=2.5))
    result = propose(Design.model_validate(design_data()), [carton], max_packages=3)
    assert result["candidates"]
    for candidate in result["candidates"]:
        assert candidate["package_count"] >= 2
        assert "payload_exceeded" not in codes(candidate["assessment"])
    heavy = Carton.model_validate(carton_data(payload=0.1))
    blocked = propose(Design.model_validate(design_data()), [heavy])
    assert blocked["candidates"] == [] and blocked["rejected"][0]["reason"] == "payload_used_by_packing"


def test_cushion_check_counts_pocket_voids_conservatively_and_ignores_invalid_inserts():
    block = Insert.model_validate({"id": "block", "name": "TEST block", "dimensions_m": [0.14, 0.08, 0.08],
        "position_m": [0, 0, 0], "density_kg_m3": 30.0, "material_evidence": "TEST",
        "pockets": [{"id": "p1", "dimensions_m": [0.102, 0.06, 0.042], "position_m": [0.019, 0.02, 0.019]}]})
    bounds = ((0.02, 0.02, 0.02), (0.12, 0.08, 0.06))
    inner = (0.14, 0.3, 0.08)
    assert foam_along(bounds, [block], 1, False, inner) == pytest.approx(0.02)
    assert foam_along(bounds, [block], 0, False, inner) == pytest.approx(0.019)
    assert foam_along(bounds, [block], 0, True, inner) == pytest.approx(0.019)
    assert foam_along(bounds, [block], 1, True, inner) == 0.0
    round_block = Insert.model_validate({"id": "round", "name": "TEST round", "dimensions_m": [0.14, 0.08, 0.14],
        "position_m": [0, 0, 0], "density_kg_m3": 30.0, "material_evidence": "TEST",
        "pockets": [{"id": "p1", "shape": "cylindrical", "dimensions_m": [0.1, 0.06, 0.1], "position_m": [0.02, 0.02, 0.02]}]})
    cube = ((0.04, 0.02, 0.04), (0.1, 0.08, 0.1))  # 60 mm cube centred in the 100 mm round pocket
    # The true wall is 20 mm on the centre line and 30 mm at the face edges; the bounding
    # square never credits more than the thinnest true wall.
    assert foam_along(cube, [round_block], 0, False, (0.14, 0.3, 0.14)) == pytest.approx(0.02)
    assert foam_along(cube, [round_block], 2, True, (0.14, 0.3, 0.14)) == pytest.approx(0.02)
    assert foam_along(cube, [round_block], 1, False, (0.14, 0.3, 0.14)) == pytest.approx(0.02)
    data = design_data(inserts=False)
    data["constraints"]["cushion"] = CUSHION | {"top_m": 0.0, "sides_m": 0.0}
    data["packages"][0]["placements"] = [{"id": "item_1", "position_m": [0.1, 0.02, 0.1]}]
    data["quantity"] = 1
    bad_pad = {"id": "pad_bad", "name": "TEST", "dimensions_m": [0.4, 0.02, 0.3], "position_m": [0, 0, 0],
               "density_kg_m3": 35.0, "material_evidence": "TEST",
               "pockets": [{"id": "p1", "dimensions_m": [0.1, 0.03, 0.1], "position_m": [0.1, 0.0, 0.1]}]}
    data["packages"][0]["inserts"] = [bad_pad]
    invalid = assess(Design.model_validate(data))
    assert "pocket_not_top_open" in codes(invalid, "error")
    assert "cushion_insufficient" in codes(invalid, "error")  # an invalid pad provides no material
    data["packages"][0]["inserts"] = [bad_pad | {"pockets": []}]
    assert "cushion_insufficient" not in codes(assess(Design.model_validate(data)))


def test_overly_detailed_inserts_are_reported_unverified_not_passed(monkeypatch):
    from ai_inspector.packaging_shipping import components
    design = Design.model_validate(design_data())
    candidate = Design.model_validate(propose(design, [Carton.model_validate(carton_data())])["candidates"][0]["design"])
    monkeypatch.setattr(components, "CUSHION_WORK_LIMIT", 0)
    result = assess(candidate)
    assert "cushion_not_verified" in codes(result, "error") and not result["rate_ready"]
    assert all(row["verified"] is False for row in result["cushion"])


def stock_design(quantity):
    stock = catalog()
    carton = Carton.model_validate(next(c for c in stock["cartons"] if c["id"] == "uline-s-15039")["carton"])
    foam = next(m["material"] for m in stock["materials"] if m["use"] == "insert")
    data = design_data(quantity=quantity, inserts=False)
    data["constraints"]["cushion"] = CUSHION | {"material": MaterialDensity.model_validate(foam).model_dump(mode="json")}
    data["packages"][0]["carton"] = carton.model_dump(mode="json")
    return Design.model_validate(data), carton


@pytest.mark.parametrize("quantity", [1, 6, 24])
def test_one_six_and_twenty_four_items_fit_the_sourced_stock_carton_with_lining(quantity):
    design, carton = stock_design(quantity)
    result = propose(design, [carton], max_packages=3)
    assert not result["truncated"] and result["candidates"], result["rejected"]
    best = result["candidates"][0]
    packed = Design.model_validate(best["design"])
    assert sum(len(p.placements) for p in packed.packages) == quantity
    assert not codes(best["assessment"], "error")
    assert best["assessment"]["total_gross_kg"] == pytest.approx(independent_gross(packed))


def test_twenty_four_items_in_an_undersized_carton_are_explicitly_infeasible():
    design, _ = stock_design(24)
    small = Carton.model_validate(carton_data(inner=(0.2, 0.12, 0.15)))
    result = propose(design, [small], max_packages=3)
    assert result["candidates"] == [] and not result["truncated"]
    assert result["rejected"] == [{"carton": "TEST carton", "reason": "does_not_fit", "packages": 3}]
