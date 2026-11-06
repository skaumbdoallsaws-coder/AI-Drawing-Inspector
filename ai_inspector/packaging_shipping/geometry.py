"""Conservative packing-envelope checks, not transport certification."""
from __future__ import annotations

import hashlib
import json
import math
from decimal import Decimal, ROUND_HALF_UP
from .models import Design
from .components import insert_geometry, intersects_insert_material, contact_evidence, foam_along

# Matches py3dbp's six orthogonal orientations. These are dimension orders,
# not arbitrary part scaling or reflections; the viewer supplies rigid rotations.
ORDERS = ((0, 1, 2), (1, 0, 2), (1, 2, 0), (2, 1, 0), (2, 0, 1), (0, 2, 1))
TOLERANCE_M = 1e-6
# Product face -> carton wall checks for a cushion requirement: (axis, toward the +axis wall, field).
CUSHION_FACES = ((0, False, "sides_m"), (0, True, "sides_m"), (1, False, "floor_m"), (1, True, "top_m"),
                 (2, False, "sides_m"), (2, True, "sides_m"))
CUSHION_LABELS = (("floor_m", "floor"), ("top_m", "top"), ("sides_m", "sides"))


def digest(value) -> str:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def oriented(dimensions, orientation):
    return tuple(dimensions[i] for i in ORDERS[orientation])


def volume(dimensions):
    return math.prod(dimensions)


def overlaps(a, b, gap=0):
    return all(min(a[1][k], b[1][k]) - max(a[0][k], b[0][k]) > -gap + TOLERANCE_M for k in range(3))


def envelope(position, dimensions):
    return tuple(position), tuple(p + d for p, d in zip(position, dimensions))


def assess(design: Design) -> dict:
    findings = []
    masses = []

    def issue(code, message, ids=(), severity="error"):
        findings.append({"code": code, "severity": severity, "message": message, "entity_ids": list(ids)})

    product = design.product
    cushion = design.constraints.cushion
    cushion_rows = []
    if product is None:
        issue("product_required", "Select a product and confirm its dimensions.")
    elif product.mass_kg is None:
        issue("mass_unknown", "Product mass is unknown. Provide a measured mass or a documented estimate.")
    if product and product.mass_basis == "estimate":
        issue("estimated_mass", "Product mass is an estimate; shipping costs are conditional on it.", severity="warning")
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
        product_mass = product.mass_kg * len(package.placements) if product and product.mass_kg is not None else None
        insert_mass = sum(shape["net_volume_m3"] * x.density_kg_m3 for shape, x in zip(shapes, package.inserts)) if all(s["valid"] for s in shapes) else None
        allowance = package.allowance_kg
        gross = None if product_mass is None or insert_mass is None or carton.tare_kg is None or allowance is None else product_mass + insert_mass + carton.tare_kg + allowance
        if product_mass is not None and insert_mass is not None and allowance is not None and carton.max_payload_kg is not None:
            if product_mass + insert_mass + allowance > carton.max_payload_kg + 1e-9:
                issue("payload_exceeded", "Contents exceed the declared carton payload limit.", ids)
        known_cost = carton.cost_usd is not None and all(x.cost_usd is not None for x in package.inserts)
        masses.append({"package_id": package.id, "product_kg": product_mass, "insert_kg": insert_mass,
                       "carton_kg": carton.tare_kg, "allowance_kg": allowance, "gross_kg": gross,
                       "outer_m": list(carton.outer_m), "materials_cost_usd": float((Decimal(str(carton.cost_usd)) + sum((Decimal(str(x.cost_usd)) for x in package.inserts), Decimal(0))).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if known_cost else None})
    if design.constraints.contents != "ordinary_nonhazardous":
        issue("contents_unconfirmed", "Confirm ordinary non-hazardous contents before requesting parcel rates.")
    issue("protection_not_evaluated", "Envelope fit only. Cushioning, support, removal and transport performance need engineering review.", severity="warning")
    errors = [f for f in findings if f["severity"] == "error"]
    result = {"design_hash": digest(design), "status": "failed" if errors else "needs_review",
              "rate_ready": not errors, "validation_level": "conservative_bounding_envelopes",
              "findings": findings, "packages": masses, "placed_quantity": count,
              "total_gross_kg": sum(x["gross_kg"] for x in masses) if masses and all(x["gross_kg"] is not None for x in masses) else None}
    if cushion is not None:
        # Least insert material found per direction, per package (geometry only, not a performance rating).
        result["cushion"] = cushion_rows
    return result
