"""What a rated weight and its contents classification rest on; recorded with every saved quote.

Nothing here upgrades a basis: a sum of component masses stays an estimate even when some components were
weighed, because insert masses are calculated from volume and a recorded density. Only a weighed packed
carton makes a package's rated weight measured. Unknown added masses are listed, never assumed.
"""
from __future__ import annotations

from .handling import BASIS_LABELS, CONTENTS_LABELS, NO_TRANSMISSION


def weight_basis(design, assessment):
    product = design.product
    packages = []
    for package, mass in zip(design.packages, assessment["packages"]):
        count = len(package.placements)
        parts = []
        if product is not None:
            calculation = product.mass_calculation
            parts.append({"part": "product", "name": product.name, "count": count, "unit_kg": product.mass_kg,
                          "basis": product.mass_basis, "evidence": product.mass_evidence,
                          "exclusions": calculation.exclusions if calculation is not None else ""})
            for item in product.additional_mass:
                parts.append({"part": "added_mass", "id": item.id, "name": item.name, "count": count,
                              "unit_kg": item.mass_kg, "basis": item.basis, "evidence": item.evidence})
        parts.append({"part": "inserts", "kg": mass.get("insert_kg"), "basis": "calculated",
                      "evidence": "Insert volume less pocket voids, times each insert's recorded material density."})
        carton = package.carton
        parts.append({"part": "carton", "kg": carton.tare_kg, "basis": "estimate" if carton.board_blank is not None else "declared",
                      "evidence": carton.tare_evidence})
        parts.append({"part": "allowance", "kg": package.allowance_kg, "basis": "declared", "evidence": package.allowance_evidence})
        weighed = package.measured_gross_kg is not None
        packages.append({"package_id": package.id, "rated_kg": mass.get("gross_kg"),
                         "basis": "weighed_packed_carton" if weighed else "sum_of_components",
                         "weighed_kg": package.measured_gross_kg, "weighed_evidence": package.measured_gross_evidence,
                         "estimated_kg": mass.get("estimated_gross_kg"), "components": parts})
    measured = bool(packages) and all(p["basis"] == "weighed_packed_carton" for p in packages)
    unknown = [item.name for item in product.additional_mass if item.mass_kg is None] if product is not None else []
    exclusions = product.mass_calculation.exclusions if product is not None and product.mass_calculation is not None else ""
    return {"status": "measured" if measured else "estimated",
            "summary": ("Weighed packed carton" + ("s" if len(packages) > 1 else "")) if measured else
                       "Estimate: sum of component masses" + (f"; excludes {len(unknown)} item(s) of unknown mass: {', '.join(unknown)}" if unknown else ""),
            "unknown_items": unknown, "exclusions": exclusions, "packages": packages}


def contents_record(design):
    constraints = design.constraints
    return {"classification": constraints.contents, "label": CONTENTS_LABELS.get(constraints.contents, constraints.contents),
            "basis": constraints.contents_basis or None,
            "basis_label": BASIS_LABELS.get(constraints.contents_basis, "not recorded"),
            "evidence": constraints.contents_evidence, "transmitted_to_carrier": False,
            "carrier_acceptance": "not_verified", "notice": NO_TRANSMISSION}
