"""Offline analytic insert and visual/physical contract regressions, in SI units."""
from copy import deepcopy
import math

import pytest
from pydantic import ValidationError

from ai_inspector.packaging_shipping.components import (
    contact_evidence, insert_geometry, intersects_insert_material, pocket_volume,
)
from ai_inspector.packaging_shipping.geometry import assess, envelope
from ai_inspector.packaging_shipping.models import (
    Appearance, BoardBlank, Carton, Design, Insert, Package, Pocket, SurfaceGraphic,
)


def pocket_data(**changes):
    return {"id": "pocket_1", "shape": "rectangular",
            "dimensions_m": [0.2, 0.08, 0.2], "position_m": [0.05, 0.02, 0.05],
            **changes}


def insert_data(**changes):
    return {"id": "insert_1", "name": "TEST foam", "dimensions_m": [0.4, 0.1, 0.3],
            "position_m": [0.05, 0.0, 0.05], "density_kg_m3": 30.0,
            "material_evidence": "TEST supplier density certificate", "cost_usd": 0.5,
            "minimum_wall_m": 0.01, "minimum_floor_m": 0.02,
            "pockets": [pocket_data()], **changes}


def carton_data(**changes):
    return {"name": "TEST carton", "inner_m": [0.8, 0.6, 0.6],
            "outer_m": [0.82, 0.62, 0.62], "tare_kg": 0.3,
            "tare_evidence": "TEST empty carton weighed", "max_payload_kg": 10.0,
            "cost_usd": 1.0, **changes}


def design_data():
    return {"name": "TEST analytic components", "quantity": 1,
            "product": {"name": "TEST measured product", "dimensions_m": [0.08, 0.04, 0.08],
                        "mass_kg": 2.0, "mass_basis": "user_measured",
                        "mass_evidence": "TEST calibrated scale"},
            "constraints": {"clearance_m": 0.0, "gap_m": 0.0,
                            "allowed_orientations": list(range(6)),
                            "contents": "ordinary_nonhazardous"},
            "packages": [{"id": "package_1", "carton": carton_data(),
                          "placements": [{"id": "product_1", "position_m": [0.16, 0.02, 0.16]}],
                          "inserts": [insert_data()], "allowance_kg": 0.05,
                          "allowance_evidence": "TEST tape and label weighed"}]}


def graphic_data(**changes):
    return {"id": "graphic_1", "text": "TEST packing label", **changes}


def blank_data(**changes):
    return {"dimensions_m": [1.2, 0.8], "quantity": 2, "mass_per_area_kg_m2": 0.5,
            "evidence": "TEST full die-cut blank including flaps; supplier basis weight",
            **changes}


def finding_codes(result):
    return {item["code"] for item in result["findings"]}


def shape_codes(result):
    return {code for code, _ in result["findings"]}


def world_box(insert, local_position, dimensions):
    position = tuple(a + b for a, b in zip(insert.position_m, local_position))
    return envelope(position, dimensions)


@pytest.mark.parametrize("shape,removed", [
    ("rectangular", 0.2 * 0.08 * 0.2),
    ("cylindrical", math.pi * 0.1 ** 2 * 0.08),
])
def test_pocket_volume_and_net_solid_use_analytic_shape(shape, removed):
    insert = Insert.model_validate(insert_data(pockets=[pocket_data(shape=shape)]))
    result = insert_geometry(insert)
    assert pocket_volume(insert.pockets[0]) == pytest.approx(removed, rel=1e-12)
    assert result["valid"] is True
    assert result["findings"] == []
    assert result["gross_volume_m3"] == pytest.approx(0.012)
    assert result["removed_volume_m3"] == pytest.approx(removed)
    assert result["net_volume_m3"] == pytest.approx(0.012 - removed)
    assert result["basis"] == "analytic_nonoverlapping_top_open_pockets"


def test_plain_pad_and_multiple_disjoint_pockets_have_distinct_volume_bases():
    plain = insert_geometry(Insert.model_validate(insert_data(pockets=[])))
    assert plain["basis"] == "analytic_rectangular_solid"
    assert plain["valid"] and plain["removed_volume_m3"] == 0
    assert plain["net_volume_m3"] == pytest.approx(0.012)
    pockets = [pocket_data(dimensions_m=[0.1, 0.08, 0.1]),
               pocket_data(id="round", shape="cylindrical", dimensions_m=[0.1, 0.06, 0.1],
                           position_m=[0.2, 0.04, 0.05])]
    result = insert_geometry(Insert.model_validate(insert_data(pockets=pockets)))
    assert result["valid"]
    assert result["net_volume_m3"] == pytest.approx(0.012 - 0.0008 - math.pi * 0.05 ** 2 * 0.06)


@pytest.mark.parametrize("shape", ["rectangular", "cylindrical"])
@pytest.mark.parametrize("axis,side", [(0, "low"), (0, "high"), (2, "low"), (2, "high")])
@pytest.mark.parametrize("intrusion,valid", [(0.0, True), (0.5e-6, True), (2e-6, False)])
def test_wall_thickness_and_tolerance_on_all_four_sides(shape, axis, side, intrusion, valid):
    data = insert_data(pockets=[pocket_data(shape=shape)])
    pocket = data["pockets"][0]
    pocket["position_m"][axis] = (0.01 - intrusion if side == "low" else
                                    data["dimensions_m"][axis] - 0.01 - 0.2 + intrusion)
    result = insert_geometry(Insert.model_validate(data))
    assert result["valid"] is valid
    assert shape_codes(result) == (set() if valid else {"pocket_wall_thin"})
    assert (result["net_volume_m3"] is not None) is valid


@pytest.mark.parametrize("shape", ["rectangular", "cylindrical"])
@pytest.mark.parametrize("intrusion,valid", [(0.0, True), (0.5e-6, True), (2e-6, False)])
def test_floor_thickness_tolerance_preserves_top_opening(shape, intrusion, valid):
    pocket = pocket_data(shape=shape, position_m=[0.05, 0.02 - intrusion, 0.05],
                         dimensions_m=[0.2, 0.08 + intrusion, 0.2])
    result = insert_geometry(Insert.model_validate(insert_data(pockets=[pocket])))
    assert result["valid"] is valid
    assert shape_codes(result) == (set() if valid else {"pocket_floor_thin"})


@pytest.mark.parametrize("delta,valid", [(-2e-6, False), (-0.5e-6, True),
                                         (0.0, True), (0.5e-6, True), (2e-6, False)])
def test_cavity_must_open_at_positive_y_not_stop_below_or_extend_above(delta, valid):
    pocket = pocket_data(dimensions_m=[0.2, 0.08 + delta, 0.2])
    result = insert_geometry(Insert.model_validate(insert_data(pockets=[pocket])))
    assert result["valid"] is valid
    assert shape_codes(result) == (set() if valid else {"pocket_not_top_open"})


@pytest.mark.parametrize("first_shape,second_shape", [
    ("rectangular", "rectangular"), ("cylindrical", "cylindrical"),
    ("rectangular", "cylindrical"), ("cylindrical", "rectangular"),
])
@pytest.mark.parametrize("gap,valid", [(-0.005, False), (0.0, False), (0.005, False),
                                       (0.01 - 2e-6, False), (0.01 - 0.5e-6, True),
                                       (0.01, True), (0.03, True)])
def test_web_thickness_is_symmetric_for_every_pocket_pair(first_shape, second_shape, gap, valid):
    pockets = [pocket_data(shape=first_shape, dimensions_m=[0.1, 0.08, 0.1]),
               pocket_data(id="second", shape=second_shape, dimensions_m=[0.1, 0.06, 0.1],
                           position_m=[0.15 + gap, 0.04, 0.05])]
    results = [insert_geometry(Insert.model_validate(insert_data(pockets=order)))
               for order in (pockets, list(reversed(pockets)))]
    for result in results:
        assert result["valid"] is valid
        assert shape_codes(result) == (set() if valid else {"pocket_web_thin"})
        assert (result["net_volume_m3"] is not None) is valid
    assert results[0]["removed_volume_m3"] == pytest.approx(results[1]["removed_volume_m3"])


@pytest.mark.parametrize("shapes,position", [
    (("rectangular", "rectangular"), [0.158, 0.02, 0.158]),
    (("cylindrical", "cylindrical"), [0.13, 0.02, 0.13]),
    (("rectangular", "cylindrical"), [0.145, 0.02, 0.145]),
])
def test_diagonal_web_uses_true_footprint_distance_not_axis_aligned_boxes(shapes, position):
    pockets = [pocket_data(shape=shapes[0], dimensions_m=[0.1, 0.08, 0.1]),
               pocket_data(id="second", shape=shapes[1], dimensions_m=[0.1, 0.08, 0.1],
                           position_m=position)]
    for order in (pockets, list(reversed(pockets))):
        assert insert_geometry(Insert.model_validate(insert_data(pockets=order)))["valid"]


def test_nonpositive_remaining_volume_is_invalid_not_zero_or_negative_mass():
    pocket = pocket_data(dimensions_m=[0.4, 0.1, 0.3], position_m=[0.0, 0.0, 0.0])
    result = insert_geometry(Insert.model_validate(insert_data(pockets=[pocket])))
    assert not result["valid"]
    assert "insert_volume_invalid" in shape_codes(result)
    assert result["net_volume_m3"] is None


@pytest.mark.parametrize("shape", ["rectangular", "cylindrical"])
@pytest.mark.parametrize("translation", [(0.0, 0.0, 0.0), (0.31, 0.27, 0.43)])
def test_void_collision_is_translation_invariant_and_allows_top_protrusion(shape, translation):
    insert = Insert.model_validate(insert_data(position_m=translation, pockets=[pocket_data(shape=shape)]))
    for height in (0.04, 0.15):
        bounds = world_box(insert, (0.11, 0.02, 0.11), (0.08, height, 0.08))
        assert not intersects_insert_material(bounds, insert)
    assert intersects_insert_material(world_box(insert, (0.11, 0.01, 0.11), (0.08, 0.04, 0.08)), insert)
    assert intersects_insert_material(world_box(insert, (0.02, 0.03, 0.11), (0.05, 0.04, 0.08)), insert)


def test_circle_diameter_box_is_not_a_safe_rectangular_product_envelope():
    insert = Insert.model_validate(insert_data(pockets=[pocket_data(shape="cylindrical")]))
    # Every side is inside the diameter box, but the four corners cut the round wall.
    assert intersects_insert_material(world_box(insert, (0.06, 0.02, 0.06), (0.18, 0.04, 0.18)), insert)
    half_side = 0.1 / math.sqrt(2)
    tangent = world_box(insert, (0.15 - half_side, 0.02, 0.15 - half_side),
                        (2 * half_side, 0.04, 2 * half_side))
    assert not intersects_insert_material(tangent, insert)
    assert intersects_insert_material(world_box(insert, (0.15 - half_side - 2e-6, 0.02, 0.15 - half_side),
                                                (2 * half_side + 4e-6, 0.04, 2 * half_side)), insert)


@pytest.mark.parametrize("position,dimensions", [
    ((0.4, 0.0, 0.0), (0.1, 0.1, 0.1)),
    ((0.0, 0.1, 0.0), (0.1, 0.1, 0.1)),
    ((0.0, 0.0, 0.3), (0.1, 0.1, 0.1)),
    ((0.5, 0.2, 0.4), (0.1, 0.1, 0.1)),
    ((0.4 - 0.5e-6, 0.0, 0.0), (0.1, 0.1, 0.1)),
])
def test_touching_or_separated_bounds_are_not_insert_collisions(position, dimensions):
    insert = Insert.model_validate(insert_data(pockets=[]))
    assert not intersects_insert_material(world_box(insert, position, dimensions), insert)


def test_product_spanning_two_voids_still_intersects_the_web():
    pockets = [pocket_data(dimensions_m=[0.1, 0.08, 0.1]),
               pocket_data(id="second", dimensions_m=[0.1, 0.08, 0.1], position_m=[0.17, 0.02, 0.05])]
    insert = Insert.model_validate(insert_data(pockets=pockets))
    assert insert_geometry(insert)["valid"]
    assert intersects_insert_material(world_box(insert, (0.06, 0.03, 0.06), (0.2, 0.04, 0.08)), insert)


def test_invalid_insert_falls_back_to_solid_envelope_and_never_claims_support():
    insert = Insert.model_validate(insert_data(minimum_floor_m=0.03))
    bounds = world_box(insert, (0.11, 0.02, 0.11), (0.08, 0.04, 0.08))
    assert not insert_geometry(insert)["valid"]
    assert intersects_insert_material(bounds, insert)
    assert not contact_evidence(bounds, insert)
    assert not intersects_insert_material(world_box(insert, (0.5, 0.2, 0.4), (0.1, 0.1, 0.1)), insert)


@pytest.mark.parametrize("shape", ["rectangular", "cylindrical"])
@pytest.mark.parametrize("translation", [(0.0, 0.0, 0.0), (0.2, 0.3, 0.4)])
def test_support_requires_floor_or_solid_top_contact_not_floating_or_void(shape, translation):
    insert = Insert.model_validate(insert_data(position_m=translation, pockets=[pocket_data(shape=shape)]))
    assert contact_evidence(world_box(insert, (0.11, 0.02, 0.11), (0.08, 0.04, 0.08)), insert)
    assert contact_evidence(world_box(insert, (0.3, 0.1, 0.1), (0.05, 0.04, 0.05)), insert)
    assert not contact_evidence(world_box(insert, (0.11, 0.04, 0.11), (0.08, 0.04, 0.08)), insert)
    assert not contact_evidence(world_box(insert, (0.11, 0.1, 0.11), (0.08, 0.04, 0.08)), insert)
    assert not contact_evidence(world_box(insert, (0.5, 0.1, 0.1), (0.05, 0.04, 0.05)), insert)


def test_zero_floor_through_pocket_has_no_material_support():
    insert = Insert.model_validate(insert_data(minimum_floor_m=0.0,
        pockets=[pocket_data(position_m=[0.05, 0.0, 0.05], dimensions_m=[0.2, 0.1, 0.2])]))
    bounds = world_box(insert, (0.11, 0.0, 0.11), (0.08, 0.04, 0.08))
    assert insert_geometry(insert)["valid"]
    assert not intersects_insert_material(bounds, insert)
    assert not contact_evidence(bounds, insert)


@pytest.mark.parametrize("shape,removed", [("rectangular", 0.0032),
                                            ("cylindrical", math.pi * 0.1 ** 2 * 0.08)])
def test_assess_uses_net_insert_volume_and_keeps_protection_warning(shape, removed):
    data = design_data()
    data["packages"][0]["inserts"][0]["pockets"][0]["shape"] = shape
    result = assess(Design.model_validate(data))
    mass = result["packages"][0]
    expected_insert = (0.012 - removed) * 30.0
    assert mass["insert_kg"] == pytest.approx(expected_insert)
    assert mass["product_kg"] == 2.0
    assert mass["carton_kg"] == 0.3
    assert mass["allowance_kg"] == 0.05
    assert mass["gross_kg"] == pytest.approx(2.35 + expected_insert)
    assert result["total_gross_kg"] == pytest.approx(mass["gross_kg"])
    assert result["rate_ready"] and result["status"] == "needs_review"
    assert result["validation_level"] == "conservative_bounding_envelopes"
    assert finding_codes(result) == {"protection_not_evaluated"}
    assert result["findings"][0]["severity"] == "warning"


@pytest.mark.parametrize("bad_insert,code", [
    (insert_data(minimum_wall_m=0.06), "pocket_wall_thin"),
    (insert_data(minimum_floor_m=0.03), "pocket_floor_thin"),
    (insert_data(pockets=[pocket_data(dimensions_m=[0.2, 0.07, 0.2])]), "pocket_not_top_open"),
    (insert_data(pockets=[pocket_data(), pocket_data(id="overlapping")]), "pocket_web_thin"),
    (insert_data(pockets=[pocket_data(dimensions_m=[0.4, 0.1, 0.3], position_m=[0.0, 0.0, 0.0])]),
     "insert_volume_invalid"),
])
def test_invalid_insert_makes_package_and_document_gross_unknown(bad_insert, code):
    data = design_data()
    bad_package = deepcopy(data["packages"][0])
    bad_package["id"] = "package_2"
    bad_package["placements"][0]["id"] = "product_2"
    bad_package["inserts"] = [bad_insert]
    data["packages"].append(bad_package)
    data["quantity"] = 2
    result = assess(Design.model_validate(data))
    assert result["packages"][0]["gross_kg"] == pytest.approx(2.614)
    bad_mass = result["packages"][1]
    assert bad_mass["insert_kg"] is None
    assert bad_mass["gross_kg"] is None
    assert bad_mass["product_kg"] == 2.0 and bad_mass["carton_kg"] == 0.3
    assert result["total_gross_kg"] is None
    assert not result["rate_ready"] and result["status"] == "failed"
    finding = next(f for f in result["findings"] if f["code"] == code)
    assert finding["severity"] == "error" and finding["entity_ids"] == ["insert_1"]


def test_multiple_products_packages_and_pad_densities_are_summed_once_each():
    data = design_data()
    first = data["packages"][0]
    first["placements"].append({"id": "product_2", "position_m": [0.6, 0.0, 0.1]})
    first["inserts"].append(insert_data(id="pad_2", position_m=[0.5, 0.0, 0.4],
        dimensions_m=[0.1, 0.02, 0.1], density_kg_m3=100.0, pockets=[]))
    second = deepcopy(first)
    second["id"] = "package_2"
    second["placements"] = [{"id": "product_3", "position_m": [0.1, 0.0, 0.1]}]
    second["inserts"] = []
    data["packages"].append(second)
    data["quantity"] = 3
    result = assess(Design.model_validate(data))
    assert result["rate_ready"]
    assert result["placed_quantity"] == 3
    assert result["packages"][0]["insert_kg"] == pytest.approx(0.264 + 0.02)
    assert result["packages"][0]["product_kg"] == 4.0
    assert result["packages"][1]["insert_kg"] == 0
    assert result["total_gross_kg"] == pytest.approx(6.0 + 0.284 + 2 * (0.3 + 0.05))


def test_one_invalid_insert_suppresses_partial_insert_mass_in_the_same_package():
    data = design_data()
    package = data["packages"][0]
    package["inserts"].append(insert_data(id="invalid_pad", position_m=[0.5, 0.0, 0.4],
        dimensions_m=[0.1, 0.02, 0.1],
        pockets=[pocket_data(dimensions_m=[0.08, 0.01, 0.08], position_m=[0.01, 0.01, 0.01])]))
    package["carton"]["max_payload_kg"] = 0.5
    result = assess(Design.model_validate(data))
    assert "pocket_floor_thin" in finding_codes(result)
    assert result["packages"][0]["insert_kg"] is None
    assert result["packages"][0]["gross_kg"] is None
    assert result["total_gross_kg"] is None
    assert not result["rate_ready"]


@pytest.mark.parametrize("unknown,code", [("product", "mass_unknown"),
                                           ("carton", "carton_mass_unknown"),
                                           ("allowance", "allowance_unknown")])
def test_visuals_never_supply_missing_physical_mass(unknown, code):
    data = design_data()
    package = data["packages"][0]
    data["product"]["appearance"] = {"metalness": 1.0}
    package["carton"]["appearance"] = {"color": "#EEDDAA"}
    package["inserts"][0]["appearance"] = {"opacity": 0.1}
    if unknown == "product":
        data["product"].update(mass_kg=None, mass_basis="unknown", mass_evidence="")
    elif unknown == "carton":
        package["carton"].update(tare_kg=None, tare_evidence="")
    else:
        package.update(allowance_kg=None, allowance_evidence="")
    result = assess(Design.model_validate(data))
    assert code in finding_codes(result)
    assert result["packages"][0]["gross_kg"] is None
    assert result["total_gross_kg"] is None and not result["rate_ready"]


@pytest.mark.parametrize("limit,exceeded", [(2.314, False), (2.313, True)])
def test_payload_uses_net_insert_mass_plus_allowance_but_not_carton_tare(limit, exceeded):
    data = design_data()
    data["packages"][0]["carton"].update(max_payload_kg=limit, tare_kg=20.0)
    result = assess(Design.model_validate(data))
    assert ("payload_exceeded" in finding_codes(result)) is exceeded
    assert result["packages"][0]["gross_kg"] == pytest.approx(22.314)


@pytest.mark.parametrize("orientation,collision", [(0, True), (1, False), (2, False),
                                                   (3, False), (4, False), (5, True)])
def test_assess_checks_all_orientation_orders_against_pocket_material(orientation, collision):
    data = design_data()
    data["product"]["dimensions_m"] = [0.1, 0.03, 0.06]
    package = data["packages"][0]
    package["inserts"][0]["pockets"][0]["dimensions_m"] = [0.08, 0.08, 0.12]
    package["placements"][0].update(position_m=[0.105, 0.02, 0.105], orientation=orientation)
    result = assess(Design.model_validate(data))
    assert ("insert_overlap" in finding_codes(result)) is collision
    assert result["rate_ready"] is not collision
    assert result["packages"][0]["product_kg"] == 2.0
    if collision:
        finding = next(f for f in result["findings"] if f["code"] == "insert_overlap")
        assert finding["entity_ids"] == ["insert_1", "product_1"]


def test_assess_reports_round_pocket_corner_collision_not_a_false_fit():
    data = design_data()
    data["product"]["dimensions_m"] = [0.18, 0.04, 0.18]
    package = data["packages"][0]
    package["inserts"][0]["pockets"][0]["shape"] = "cylindrical"
    package["placements"][0]["position_m"] = [0.11, 0.02, 0.11]
    result = assess(Design.model_validate(data))
    assert "insert_overlap" in finding_codes(result)
    assert not result["rate_ready"]


@pytest.mark.parametrize("y,supported", [(0.02, True), (0.03, False), (0.1, False)])
def test_assess_support_warning_is_evidence_not_a_transport_certificate(y, supported):
    data = design_data()
    data["packages"][0]["placements"][0]["position_m"][1] = y
    result = assess(Design.model_validate(data))
    assert ("support_not_verified" in finding_codes(result)) is not supported
    assert "protection_not_evaluated" in finding_codes(result)
    assert result["status"] == "needs_review" and result["rate_ready"]
    if not supported:
        finding = next(f for f in result["findings"] if f["code"] == "support_not_verified")
        assert finding["severity"] == "warning" and finding["entity_ids"] == ["package_1"]


def test_insert_outside_carton_and_insert_insert_overlap_remain_conservative():
    data = design_data()
    package = data["packages"][0]
    package["inserts"].append(insert_data(id="pad_2", position_m=[0.35, 0.0, 0.05], pockets=[]))
    result = assess(Design.model_validate(data))
    finding = next(f for f in result["findings"] if f["code"] == "insert_overlap")
    assert finding["entity_ids"] == ["pad_2", "insert_1"]
    package["inserts"][1]["position_m"] = [0.5, 0.0, 0.05]
    result = assess(Design.model_validate(data))
    assert "insert_outside_carton" in finding_codes(result)
    assert "insert_overlap" not in finding_codes(result)
    assert not result["rate_ready"]


def test_appearance_defaults_and_json_roundtrip():
    assert Appearance().model_dump() == {"color": "#9BA1A6", "roughness": 0.55,
                                         "metalness": 0.0, "opacity": 1.0}
    appearance = Appearance(color="#aBcD09", roughness=0.0, metalness=1.0, opacity=0.01)
    assert Appearance.model_validate_json(appearance.model_dump_json()) == appearance


@pytest.mark.parametrize("color", ["red", "#fff", "#00000000", "000000", "#GG0000", "#123456\n", None])
def test_appearance_requires_six_digit_hex_color(color):
    with pytest.raises(ValidationError):
        Appearance(color=color)


@pytest.mark.parametrize("field", ["roughness", "metalness", "opacity"])
@pytest.mark.parametrize("bad", [-0.001, 1.001, float("nan"), float("inf"), -float("inf"), True, "0.5"])
def test_appearance_rejects_out_of_range_nonfinite_and_coerced_values(field, bad):
    with pytest.raises(ValidationError):
        Appearance.model_validate({field: bad})


def test_opacity_cannot_hide_an_object_with_zero_and_assignment_is_validated():
    with pytest.raises(ValidationError):
        Appearance(opacity=0.0)
    appearance = Appearance()
    with pytest.raises(ValidationError):
        appearance.opacity = 0.0
    assert appearance.opacity == 1.0


@pytest.mark.parametrize("field,value", [("density_kg_m3", 1000.0), ("mass_kg", 2.0),
                                          ("material", "steel"), ("texture_url", "https://example.invalid/x")])
def test_visual_appearance_is_closed_and_has_no_physical_or_external_asset_fields(field, value):
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Appearance.model_validate({field: value})


@pytest.mark.parametrize("field,bad", [
    ("dimensions_m", [1.0]), ("dimensions_m", [1.0, 1.0, 1.0]),
    ("dimensions_m", [0.0, 1.0]), ("dimensions_m", [5.001, 1.0]),
    ("dimensions_m", [float("nan"), 1.0]), ("dimensions_m", ["1", 1.0]),
    ("quantity", 0), ("quantity", 21), ("quantity", 1.0), ("quantity", True),
    ("mass_per_area_kg_m2", 0.0), ("mass_per_area_kg_m2", 25.001),
    ("mass_per_area_kg_m2", float("inf")), ("mass_per_area_kg_m2", "0.5"),
    ("mass_per_area_kg_m2", True), ("evidence", ""), ("evidence", " \t\n"),
    ("evidence", "x" * 501), ("density_kg_m3", 20.0),
])
def test_board_blank_contract_rejects_invalid_or_undocumented_input(field, bad):
    with pytest.raises(ValidationError):
        BoardBlank.model_validate(blank_data(**{field: bad}))


def test_full_blank_area_quantity_and_basis_weight_determine_tare_not_carton_surface_area():
    blank = BoardBlank.model_validate(blank_data())
    assert BoardBlank.model_validate_json(blank.model_dump_json()) == blank
    assert BoardBlank.model_validate(blank_data(quantity=20, mass_per_area_kg_m2=25.0)).quantity == 20
    data = design_data()
    data["packages"][0]["carton"].update(board_blank=blank.model_dump(), tare_kg=0.96)
    result = assess(Design.model_validate(data))
    assert result["packages"][0]["carton_kg"] == pytest.approx(1.2 * 0.8 * 2 * 0.5)
    assert result["packages"][0]["gross_kg"] == pytest.approx(2.0 + 0.264 + 0.96 + 0.05)
    finding = next(f for f in result["findings"] if f["code"] == "estimated_carton_mass")
    assert finding["severity"] == "warning" and finding["entity_ids"] == ["package_1"]
    assert result["rate_ready"] and result["status"] == "needs_review"


@pytest.mark.parametrize("tare", [None, 0.0, 0.48, 0.960001])
def test_blank_requires_matching_tare_including_quantity(tare):
    with pytest.raises(ValidationError, match="full-blank"):
        Carton.model_validate(carton_data(board_blank=blank_data(), tare_kg=tare))


def test_blank_matching_tolerance_does_not_remove_tare_evidence_requirement():
    assert Carton.model_validate(carton_data(board_blank=blank_data(), tare_kg=0.96 + 5e-9)).board_blank
    with pytest.raises(ValidationError, match="empty-carton"):
        Carton.model_validate(carton_data(board_blank=blank_data(), tare_kg=0.96, tare_evidence=" "))


@pytest.mark.parametrize("face", ["x-", "x+", "y-", "y+", "z-", "z+"])
@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_surface_graphic_faces_quarter_turns_and_json_roundtrip(face, rotation):
    graphic = SurfaceGraphic.model_validate(graphic_data(face=face, rotation_degrees=rotation))
    assert graphic.target == "carton" and graphic.target_id is None
    assert graphic.kind == "text" and graphic.image_id is None
    assert graphic.face == face and graphic.rotation_degrees == rotation
    assert SurfaceGraphic.model_validate_json(graphic.model_dump_json()) == graphic


@pytest.mark.parametrize("changes", [
    {"text": ""}, {"text": " \t"}, {"text": "x" * 501}, {"image_id": "image_1"},
    {"kind": "image", "text": ""}, {"kind": "image", "image_id": "image_1"},
    {"kind": "image", "text": " ", "image_id": "image_1"},
    {"kind": "image", "text": "", "image_id": "../image"},
    {"target": "insert"}, {"target_id": "insert_1"}, {"target": "product"},
    {"target": "insert", "target_id": "../insert"}, {"face": "top"},
    {"rotation_degrees": 45}, {"rotation_degrees": -90}, {"rotation_degrees": 360},
    {"color": "transparent"}, {"image_url": "https://example.invalid/image.png"},
    {"mass_kg": 1.0}, {"kind": "svg"},
])
def test_surface_graphic_exclusive_content_target_and_closed_contract(changes):
    with pytest.raises(ValidationError):
        SurfaceGraphic.model_validate(graphic_data(**changes))


@pytest.mark.parametrize("field", ["u", "v", "width_fraction", "height_fraction"])
@pytest.mark.parametrize("bad", [-0.001, 1.001, float("nan"), float("inf"), True, "0.5"])
def test_graphic_fraction_fields_are_finite_strict_and_bounded(field, bad):
    with pytest.raises(ValidationError):
        SurfaceGraphic.model_validate(graphic_data(**{field: bad}))


@pytest.mark.parametrize("changes", [
    {"width_fraction": 0.0}, {"height_fraction": 0.0},
    {"u": 0.0}, {"u": 1.0}, {"v": 0.0}, {"v": 1.0},
    {"u": 0.1, "width_fraction": 0.21}, {"u": 0.9, "width_fraction": 0.21},
    {"v": 0.1, "height_fraction": 0.21}, {"v": 0.9, "height_fraction": 0.21},
])
def test_graphic_region_cannot_extend_past_any_face_edge(changes):
    with pytest.raises(ValidationError):
        SurfaceGraphic.model_validate(graphic_data(**changes))


def test_graphic_full_face_and_exact_edge_fits_are_accepted_without_clamping():
    full = SurfaceGraphic.model_validate(graphic_data(width_fraction=1.0, height_fraction=1.0))
    assert full.width_fraction == full.height_fraction == 1.0
    for u, v in [(0.1, 0.1), (0.9, 0.9)]:
        graphic = SurfaceGraphic.model_validate(graphic_data(u=u, v=v, width_fraction=0.2, height_fraction=0.2))
        assert (graphic.u, graphic.v) == (u, v)


def test_graphic_ids_are_unique_and_insert_targets_are_package_local():
    package = design_data()["packages"][0]
    image = graphic_data(target="insert", target_id="insert_1", kind="image", text="", image_id="image_1")
    package["graphics"] = [image]
    assert Package.model_validate(package).graphics[0].image_id == "image_1"
    package["graphics"].append(deepcopy(image))
    with pytest.raises(ValidationError, match="Graphic IDs"):
        Package.model_validate(package)
    package["graphics"] = [dict(image, target_id="product_1")]
    with pytest.raises(ValidationError, match="existing insert"):
        Package.model_validate(package)
    data = design_data()
    other = deepcopy(data["packages"][0])
    other.update(id="package_2", placements=[], inserts=[], graphics=[image])
    data["packages"].append(other)
    with pytest.raises(ValidationError, match="existing insert"):
        Design.model_validate(data)


def test_graphic_and_pocket_count_limits_and_pocket_id_uniqueness():
    package = design_data()["packages"][0]
    package["graphics"] = [graphic_data(id=f"graphic_{i}") for i in range(16)]
    assert len(Package.model_validate(package).graphics) == 16
    package["graphics"].append(graphic_data(id="overflow"))
    with pytest.raises(ValidationError):
        Package.model_validate(package)
    with pytest.raises(ValidationError, match="Pocket IDs"):
        Insert.model_validate(insert_data(pockets=[pocket_data(), pocket_data()]))
    with pytest.raises(ValidationError):
        Insert.model_validate(insert_data(pockets=[pocket_data(id=f"pocket_{i}") for i in range(17)]))


@pytest.mark.parametrize("changes", [
    {"shape": "sphere"}, {"shape": "cylindrical", "dimensions_m": [0.2, 0.08, 0.19]},
    {"dimensions_m": [0.2, 0.0, 0.2]}, {"dimensions_m": [0.2, float("nan"), 0.2]},
    {"position_m": [0.0, -0.01, 0.0]}, {"position_m": [0.0, True, 0.0]},
    {"rotation_degrees": 45}, {"density_kg_m3": 100.0},
])
def test_pocket_model_restricts_geometry_to_closed_analytic_contract(changes):
    with pytest.raises(ValidationError):
        Pocket.model_validate(pocket_data(**changes))


@pytest.mark.parametrize("changes", [
    {"density_kg_m3": 0.0}, {"density_kg_m3": 25001.0}, {"density_kg_m3": float("nan")},
    {"density_kg_m3": True}, {"density_kg_m3": "30"}, {"material_evidence": ""},
    {"material_evidence": " \t\n"}, {"material_evidence": "x" * 501},
    {"minimum_wall_m": 0.0009}, {"minimum_wall_m": 0.201},
    {"minimum_floor_m": -0.001}, {"minimum_floor_m": 0.201},
])
def test_insert_requires_documented_density_and_bounded_wall_floor_values(changes):
    with pytest.raises(ValidationError):
        Insert.model_validate(insert_data(**changes))


@pytest.mark.parametrize("estimated_product", [False, True])
def test_appearance_and_graphics_change_document_identity_but_never_mass_or_collisions(estimated_product):
    data = design_data()
    if estimated_product:
        data["product"].update(mass_basis="estimate", mass_evidence="TEST documented density estimate",
            mass_calculation={"volume_m3": 0.001,
                              "material": {"name": "TEST alloy", "density_kg_m3": 2000.0,
                                           "evidence": "TEST supplier density"}})
    original = assess(Design.model_validate(data))
    package = data["packages"][0]
    data["product"]["appearance"] = {"color": "#FF0000", "roughness": 0.0, "metalness": 1.0}
    package["carton"]["appearance"] = {"color": "#00FF00", "opacity": 0.1}
    package["inserts"][0]["appearance"] = {"color": "#0000FF", "roughness": 1.0, "opacity": 0.01}
    package["graphics"] = [graphic_data(), graphic_data(id="insert_label", target="insert", target_id="insert_1",
        kind="image", text="", image_id="image_1", width_fraction=1.0, height_fraction=1.0)]
    styled_design = Design.model_validate(data)
    styled = assess(styled_design)
    assert styled["design_hash"] != original["design_hash"]
    assert {k: v for k, v in styled.items() if k != "design_hash"} == {
        k: v for k, v in original.items() if k != "design_hash"}
    assert Design.model_validate_json(styled_design.model_dump_json()) == styled_design
    if estimated_product:
        assert "estimated_mass" in finding_codes(styled)
        data["product"]["mass_kg"] = 2.1
        with pytest.raises(ValidationError, match="Density-based mass"):
            Design.model_validate(data)
