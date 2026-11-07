"""Sourced stock-carton catalog (P3): records as the supplier pages state them, and selection through the proposer.

The carton values were read from each ULINE product page on 2026-11-06 (see catalog.py). These tests check the
transcription for internal consistency and show the proposer choosing among catalog cartons for a synthetic TEST
product. They make no network request and are not a supplier re-check, a price or a load rating."""
from __future__ import annotations

import pytest

from ai_inspector.packaging_shipping.catalog import CARTONS_CHECKED, INCH_M, POUND_KG, catalog
from ai_inspector.packaging_shipping.models import Carton, Design, MaterialDensity
from ai_inspector.packaging_shipping.packing import propose


def cartons():
    return catalog()["cartons"]


def test_every_carton_is_a_sourced_uline_record_with_its_page_values():
    entries = cartons()
    assert len(entries) == 9 and len({e["id"] for e in entries}) == 9 and len({e["carton"]["sku"] for e in entries}) == 9
    for entry in entries:
        carton = Carton.model_validate(entry["carton"]).model_dump(mode="json")
        assert carton == entry["carton"]
        sku = carton["sku"]
        assert entry["id"] == "uline-" + sku.lower() and carton["supplier"] == "ULINE"
        assert carton["source_url"].startswith(f"https://www.uline.com/Product/Detail/{sku}/Corrugated-Boxes-200-Test/")
        assert carton["tare_evidence"].endswith(f"Checked {CARTONS_CHECKED}. {carton['source_url']}")
        assert entry["checked_at"] == CARTONS_CHECKED and entry["grade"].startswith("200 lb test")
        assert entry["purchase_multiple"] in {10, 20, 25} and entry["outer_tolerance_m"] == pytest.approx(.125 * INCH_M)
        # The pages state outside = inside + 3/8 in on length and width and + 5/8 in on height (X/Y/Z = L/H/W).
        grow = [(o - i) / INCH_M for i, o in zip(carton["inner_m"], carton["outer_m"])]
        assert grow == pytest.approx([.375, .625, .375])
        # No price, payload or board blank is invented.
        assert carton["cost_usd"] is None and carton["max_payload_kg"] is None and carton["board_blank"] is None
    volumes = [e["carton"]["inner_m"][0] * e["carton"]["inner_m"][1] * e["carton"]["inner_m"][2] for e in entries]
    assert volumes == sorted(volumes)


def test_unit_weights_are_consistent_with_regular_slotted_carton_board_area():
    """Transcription guard, not a physical claim: an RSC blank is about (2(L+W) + 1.25 in) x (W + H), and the stated
    unit weights all give about 0.12 lb/ft2, typical of 200 lb test board. A misread weight (0.26 vs 2.6) would fail."""
    for entry in cartons():
        carton = entry["carton"]
        length, height, width = (x / INCH_M for x in carton["inner_m"])
        blank_ft2 = (2 * (length + width) + 1.25) * (width + height) / 144
        pounds = carton["tare_kg"] / POUND_KG
        assert .10 < pounds / blank_ft2 < .14, (carton["sku"], pounds / blank_ft2)


def test_the_proposer_selects_the_smallest_feasible_catalog_carton_and_says_why_others_fail():
    entries = cartons()
    foam = next(m["material"] for m in catalog()["materials"] if m["id"] == "ethafoam-220-0924")
    design = Design.model_validate({
        "name": "TEST catalog selection", "quantity": 1,
        "product": {"name": "TEST bar", "dimensions_m": [0.30, 0.04, 0.10], "mass_kg": 0.2,
                    "mass_basis": "user_measured", "mass_evidence": "TEST scale"},
        "constraints": {"contents": "ordinary_nonhazardous",
                        "cushion": {"floor_m": 0.01, "top_m": 0.01, "sides_m": 0.01, "evidence": "TEST requirement",
                                    "material": MaterialDensity.model_validate(foam).model_dump(mode="json")}},
        "packages": [{"id": "box_1", "carton": entries[-1]["carton"], "placements": [],
                      "allowance_kg": 0.05, "allowance_evidence": "TEST tape"}],
    })
    result = propose(design, [Carton.model_validate(e["carton"]) for e in entries[:6]], max_packages=1)
    chosen = [c["design"]["packages"][0]["carton"]["sku"] for c in result["candidates"]]
    # The 0.32 m lined length rules out the 8, 10 and 12 in cartons; the rest rank by outer volume.
    assert chosen == ["S-4187", "S-4235", "S-4415"]
    assert {(r["carton"], r["reason"]) for r in result["rejected"]} == {
        (f"ULINE {sku} {size} in", "does_not_fit") for sku, size in
        (("S-4080", "8 x 6 x 4"), ("S-4103", "10 x 8 x 6"), ("S-4120", "12 x 10 x 8"))}
    best = result["candidates"][0]
    assert best["assessment"]["rate_ready"] and best["design"]["packages"][0]["carton"]["tare_kg"] == pytest.approx(.92 * POUND_KG)
    assert result["preservation"]["cushion"] == "rebuilt_from_requirement"
