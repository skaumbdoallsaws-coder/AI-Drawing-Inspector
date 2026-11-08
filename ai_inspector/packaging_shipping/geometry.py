"""Conservative packing-envelope checks, not transport certification."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from .models import Design
from .components import insert_geometry, intersects_insert_material, contact_evidence, foam_along
from .handling import UNSUPPORTED_CONTENTS
from .restraint import TOTAL_WORK_LIMIT, package_restraint

# Matches py3dbp's six orthogonal orientations. These are dimension orders,
# not arbitrary part scaling or reflections; the viewer supplies rigid rotations.
ORDERS = ((0, 1, 2), (1, 0, 2), (1, 2, 0), (2, 1, 0), (2, 0, 1), (0, 2, 1))
TOLERANCE_M = 1e-6
# Product face -> carton wall checks for a cushion requirement: (axis, toward the +axis wall, field).
CUSHION_FACES = ((0, False, "sides_m"), (0, True, "sides_m"), (1, False, "floor_m"), (1, True, "top_m"),
                 (2, False, "sides_m"), (2, True, "sides_m"))
CUSHION_LABELS = (("floor_m", "floor"), ("top_m", "top"), ("sides_m", "sides"))
# Product faces in the product's own axes, before any packing orientation: (product axis, outward toward +axis).
FACES = {"x_min": (0, False), "x_max": (0, True), "y_min": (1, False), "y_max": (1, True), "z_min": (2, False), "z_max": (2, True)}


def digest(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def unit_mass(product):
    """Rated mass of one product item: its main mass plus every added mass that is known; None if the main mass is unknown.
    Unknown added items are left out here and reported by assess() and with every quote."""
    if product is None or product.mass_kg is None:
        return None
    return product.mass_kg + sum(item.mass_kg for item in product.additional_mass if item.mass_kg is not None)


def oriented(dimensions, orientation):
    return tuple(dimensions[i] for i in ORDERS[orientation])


def volume(dimensions):
    return math.prod(dimensions)


def overlaps(a, b, gap=0):
    return all(min(a[1][k], b[1][k]) - max(a[0][k], b[0][k]) > -gap + TOLERANCE_M for k in range(3))


def envelope(position, dimensions):
    return tuple(position), tuple(p + d for p, d in zip(position, dimensions))


def product_axes(orientation):
    """Per product axis: (carton axis, mirrored), matching the viewer's rigid rotation.

    Carton axis i shows product axis ORDERS[o][i]. For odd dimension orders the viewer mirrors
    carton X so the rotation stays proper (orientationRows in static/packaging.js).
    """
    order = ORDERS[orientation]
    odd = sum(1 for i in range(3) for j in range(i + 1, 3) if order[i] > order[j]) % 2
    return tuple((order.index(a), bool(odd) and order.index(a) == 0) for a in range(3))


def no_contact_zone(box, dimensions, orientation, region):
    """The air a no-contact region needs in carton axes: its area, extended air_gap_m out of the face.

    Returns (zone, carton axis, toward the carton's +axis wall).
    """
    axes = product_axes(orientation)
    lower, upper = list(box[0]), list(box[1])
    axis, outward = FACES[region.face]
    if region.area is not None:
        for k, (start, end) in zip((k for k in range(3) if k != axis), (region.area.u_m, region.area.v_m)):
            i, mirrored = axes[k]
            if mirrored:
                start, end = dimensions[k] - end, dimensions[k] - start
            lower[i], upper[i] = box[0][i] + start, box[0][i] + end
    i, mirrored = axes[axis]
    toward_max = outward != mirrored
    if toward_max:
        lower[i], upper[i] = box[1][i], box[1][i] + region.air_gap_m
    else:
        lower[i], upper[i] = box[0][i] - region.air_gap_m, box[0][i]
    return (tuple(lower), tuple(upper)), i, toward_max


def assess(design: Design) -> dict:
    findings = []
    masses = []

    def issue(code, message, ids=(), severity="error"):
        findings.append({"code": code, "severity": severity, "message": message, "entity_ids": list(ids)})

    product = design.product
    cushion = design.constraints.cushion
    cushion_rows = []
    regions, region_rows = [], []
    if product is not None:
        for region in design.constraints.no_contact:
            axis = FACES[region.face][0]
            others = [product.dimensions_m[k] for k in range(3) if k != axis]
            if region.area is not None and (region.area.u_m[1] > others[0] + TOLERANCE_M or region.area.v_m[1] > others[1] + TOLERANCE_M):
                issue("no_contact_area_outside", f"No-contact region {region.name} extends beyond its product face.", (region.id,))
            else:
                regions.append(region)
    if product is None:
        issue("product_required", "Select a product and confirm its dimensions.")
    elif product.mass_kg is None:
        issue("mass_unknown", "Product mass is unknown. Provide a measured mass or a documented estimate.")
    # A weighed packed carton is the rated weight, so component estimates no longer condition the price.
    weighed = bool(design.packages) and all(p.measured_gross_kg is not None for p in design.packages)
    if product and product.mass_basis == "estimate" and not weighed:
        issue("estimated_mass", "Product mass is an estimate; shipping costs are conditional on it.", severity="warning")
    if product and not weighed:
        unknown = [m for m in product.additional_mass if m.mass_kg is None]
        if unknown:
            issue("added_mass_unknown", f"Product mass leaves out {len(unknown)} item(s) of unknown mass: "
                  f"{', '.join(m.name for m in unknown)}. Rated weights exclude them; weigh them or one packed carton.",
                  [m.id for m in unknown], "warning")
        estimated = [m.id for m in product.additional_mass if m.basis == "estimate"]
        if estimated:
            issue("added_mass_estimated", "Some added product mass is an estimate; shipping costs are conditional on it.", estimated, "warning")
    restraint_rows, restraint_budget = [], [TOTAL_WORK_LIMIT]
    if not design.packages:
        issue("packages_required", "Add a carton and place the products.")
    count = sum(len(p.placements) for p in design.packages)
    if count != design.quantity:
        issue("quantity_mismatch", f"Expected {design.quantity} products; found {count} placed.")
    for package in design.packages:
        carton = package.carton
        boxes = []
        ids = (package.id,)
        if not package.placements:
            issue("empty_package", "A shipping package has no product instances.", ids)
        if carton.tare_kg is None:
            issue("carton_mass_unknown", "Empty-carton weight is unknown.", ids)
        if package.allowance_kg is None:
            issue("allowance_unknown", "Confirm the allowance for tape and other packing materials.", ids)
        if carton.max_payload_kg is None:
            issue("load_limit_unknown", "Carton payload capacity has not been verified.", ids, "warning")
        if carton.board_blank is not None:
            issue("estimated_carton_mass", "Carton tare uses a full-blank area estimate; verify the manufactured carton.", ids, "warning")
        for item in package.placements:
            if product is None:
                continue
            if item.orientation not in design.constraints.allowed_orientations:
                issue("orientation_forbidden", "Product orientation is not permitted.", (item.id,))
            box = envelope(item.position_m, oriented(product.dimensions_m, item.orientation))
            margin = design.constraints.clearance_m
            if any(box[0][i] < margin - TOLERANCE_M or box[1][i] > carton.inner_m[i] - margin + TOLERANCE_M for i in range(3)):
                issue("outside_usable_carton", "Product envelope violates the carton clearance.", (item.id,))
            for other_id, other_box, is_product in boxes:
                if overlaps(box, other_box, design.constraints.gap_m if is_product else 0):
                    issue("envelope_overlap", "Product envelopes overlap or violate the required separation.", (item.id, other_id))
            boxes.append((item.id, box, True))
        for insert in package.inserts:
            shape = insert_geometry(insert)
            for code, message in shape["findings"]:
                issue(code, message, (insert.id,))
            box = envelope(insert.position_m, insert.dimensions_m)
            if any(box[1][i] > carton.inner_m[i] + TOLERANCE_M for i in range(3)):
                issue("insert_outside_carton", "Packing component extends outside the carton.", (insert.id,))
            for other_id, other_box, is_product in boxes:
                intersection = intersects_insert_material(other_box, insert) if is_product else overlaps(box, other_box)
                if intersection:
                    issue("insert_overlap", "Packing component intersects another component's envelope.", (insert.id, other_id))
            boxes.append((insert.id, box, False))
        if product and package.inserts:
            unsupported = [item.id for item in package.placements
                           if item.position_m[1] > TOLERANCE_M
                           and not any(contact_evidence(envelope(item.position_m, oriented(product.dimensions_m, item.orientation)), i)
                                       for i in package.inserts)]
            if unsupported:
                issue("support_not_verified", "Some elevated products have no detected contact with an insert support. Review the packing sequence and support.", ids, "warning")
        if regions and package.placements:
            products = [(item.id, envelope(item.position_m, oriented(product.dimensions_m, item.orientation))) for item in package.placements]
            for region in regions:
                touching, down = [], 0
                for item, (item_id, box) in zip(package.placements, products):
                    zone, axis, toward_max = no_contact_zone(box, product.dimensions_m, item.orientation, region)
                    wall = zone[1][axis] > carton.inner_m[axis] + TOLERANCE_M if toward_max else zone[0][axis] < -TOLERANCE_M
                    if (wall or any(other_id != item_id and overlaps(zone, other) for other_id, other in products)
                            or any(intersects_insert_material(zone, insert) for insert in package.inserts)):
                        touching.append(item_id)
                    down += axis == 1 and not toward_max
                if touching:
                    issue("no_contact_violated", f"Packing material, a carton wall or another product is within the {region.air_gap_m * 1000:.1f} mm "
                          f"air gap of no-contact region {region.name} for {len(touching)} of {len(package.placements)} products.", (touching[0], region.id))
                if down:
                    issue("no_contact_faces_down", f"No-contact region {region.name} faces the carton floor for {down} products. Support is not "
                          "modelled beyond insert contact; confirm how the product is held off this region.", (package.id, region.id), "warning")
                region_rows.append({"package_id": package.id, "region_id": region.id, "products": len(package.placements),
                                    "touching": len(touching), "facing_down": down})
        shapes = [insert_geometry(x) for x in package.inserts]
        if cushion is not None and product is not None and package.placements:
            valid = [x for x, shape in zip(package.inserts, shapes) if shape["valid"]]
            least = {field: None for field, _ in CUSHION_LABELS}
            short, unverified = [], []
            for item in package.placements:
                box = envelope(item.position_m, oriented(product.dimensions_m, item.orientation))
                for axis, toward_max, field in CUSHION_FACES:
                    required = getattr(cushion, field)
                    if required <= 0:
                        continue
                    found = foam_along(box, valid, axis, toward_max, carton.inner_m)
                    if found is None:
                        unverified.append(item.id)
                        continue
                    least[field] = found if least[field] is None else min(least[field], found)
                    if found < required - TOLERANCE_M:
                        short.append(item.id)
            short, unverified = list(dict.fromkeys(short)), list(dict.fromkeys(unverified))
            if unverified:
                issue("cushion_not_verified", f"Cushioning could not be checked within the analysis limit for {len(unverified)} "
                      "product(s). Simplify the inserts or review them manually.", (package.id, unverified[0]))
            if short:
                parts = [f"{label} {least[field] * 1000:.1f} of {getattr(cushion, field) * 1000:.1f} mm" for field, label in CUSHION_LABELS
                         if least[field] is not None and least[field] < getattr(cushion, field) - TOLERANCE_M]
                issue("cushion_insufficient", f"Insert material is below the cushion requirement for {len(short)} of "
                      f"{len(package.placements)} products (least found: {'; '.join(parts)}).", (package.id, short[0]))
            cushion_rows.append({"package_id": package.id, "verified": not unverified,
                                 **{field: None if least[field] is None else round(least[field], 9) for field, _ in CUSHION_LABELS}})
        if product is not None and package.placements:
            restraint_rows.extend(package_restraint(
                package.id, [(item.id, envelope(item.position_m, oriented(product.dimensions_m, item.orientation))) for item in package.placements],
                [x for x, shape in zip(package.inserts, shapes) if shape["valid"]], carton.inner_m, restraint_budget))
        unit = unit_mass(product)
        product_mass = unit * len(package.placements) if unit is not None else None
        insert_mass = sum(shape["net_volume_m3"] * x.density_kg_m3 for shape, x in zip(shapes, package.inserts)) if all(s["valid"] for s in shapes) else None
        allowance = package.allowance_kg
        estimate = None if product_mass is None or insert_mass is None or carton.tare_kg is None or allowance is None else product_mass + insert_mass + carton.tare_kg + allowance
        gross = package.measured_gross_kg if package.measured_gross_kg is not None else estimate
        if product_mass is not None and insert_mass is not None and allowance is not None and carton.max_payload_kg is not None:
            if product_mass + insert_mass + allowance > carton.max_payload_kg + 1e-9:
                issue("payload_exceeded", "Contents exceed the declared carton payload limit.", ids)
        known_cost = carton.cost_usd is not None and all(x.cost_usd is not None for x in package.inserts)
        masses.append({"package_id": package.id, "product_kg": product_mass, "insert_kg": insert_mass,
                       "carton_kg": carton.tare_kg, "allowance_kg": allowance, "gross_kg": gross,
                       "estimated_gross_kg": estimate,
                       "gross_basis": None if gross is None else "measured" if package.measured_gross_kg is not None else "estimated",
                       "outer_m": list(carton.outer_m), "materials_cost_usd": float((Decimal(str(carton.cost_usd)) + sum((Decimal(str(x.cost_usd)) for x in package.inserts), Decimal(0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if known_cost else None})
    if restraint_rows:
        requirement = design.constraints.restraint
        limit = requirement.max_travel_m if requirement else 0.0
        unverified = [r for r in restraint_rows if not r["verified"]]
        moving = [r for r in restraint_rows if r["max_travel_m"] is not None and r["max_travel_m"] > limit + TOLERANCE_M]
        touching = [r for r in restraint_rows if r["reaches_products"]]
        if unverified:
            issue("restraint_not_verified", f"Translational clearance could not be predicted within the analysis limit for "
                  f"{len(unverified)} product(s). Simplify the inserts or review them manually.", (unverified[0]["item_id"],), "warning")
        if moving:
            worst = max(moving, key=lambda r: r["max_travel_m"])
            text = (f"Under the bounding-box model, {len(moving)} of {len(restraint_rows)} products have predicted translational "
                    f"clearance before they meet packing material, another product or a carton wall (up to "
                    f"{worst['max_travel_m'] * 1000:.1f} mm, {worst['max_travel_direction']}, {worst['item_id']})")
            if requirement:
                issue("restraint_insufficient", f"{text}; the restraint requirement allows {requirement.max_travel_m * 1000:.1f} mm.", (worst["item_id"],))
            else:
                issue("restraint_movement", f"{text}. Rotation, foam compression and shipping protection remain unverified.", (worst["item_id"],), "warning")
        if touching:
            first = touching[0]
            issue("products_can_touch", f"Under the bounding-box model, {len(touching)} products meet another product, not packing "
                  f"material, in at least one direction ({first['item_id']} reaches {', '.join(first['reaches_products'])}).", (first["item_id"], first["reaches_products"][0]),
                  "error" if requirement and requirement.separate_products else "warning")
    contents = design.constraints.contents
    if contents == "unconfirmed":
        issue("contents_unconfirmed", "Confirm ordinary non-hazardous contents before requesting parcel rates.")
    elif contents != "ordinary_nonhazardous":
        issue("contents_unsupported", UNSUPPORTED_CONTENTS[contents])
    elif design.constraints.contents_basis == "test_assumption":
        issue("contents_test_assumption", "Ordinary contents are a test assumption for this design, not a declaration about a real "
              "product. Its rates are not clearance to ship any product.", severity="warning")
    issue("protection_not_evaluated", "Envelope fit only. Cushioning, support, removal and transport performance need engineering review.", severity="warning")
    errors = [f for f in findings if f["severity"] == "error"]
    result = {"design_hash": digest(design), "status": "failed" if errors else "needs_review",
              "rate_ready": not errors, "validation_level": "conservative_bounding_envelopes",
              "findings": findings, "packages": masses, "placed_quantity": count,
              "total_gross_kg": sum(x["gross_kg"] for x in masses) if masses and all(x["gross_kg"] is not None for x in masses) else None}
    if cushion is not None:
        # Least insert material found per direction, per package (geometry only, not a performance rating).
        result["cushion"] = cushion_rows
    if design.constraints.no_contact:
        result["no_contact"] = region_rows
    if restraint_rows:
        # Free travel per product and direction on bounding boxes (geometry only, never a protection result).
        result["restraint"] = restraint_rows
    return result
