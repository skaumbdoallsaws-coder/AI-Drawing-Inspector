"""Bounded py3dbp search; every candidate is independently revalidated.

A proposal never sheds protection or packing mass to look smaller or lighter: a
design with inserts needs an explicit cushion requirement, which every candidate
rebuilds as a foam lining, and packing allowances come from an explicit rule or a
value every saved package already agrees on. Anything else stays unknown and blocks
rating.
"""
from __future__ import annotations

from decimal import Decimal
import math
import time
from .geometry import FACES, ORDERS, assess, digest
from .models import Design, Insert, Package, Placement
from .service import PackagingError

# A candidate with any of these findings is not a feasible arrangement.
GEOMETRIC_ERRORS = {"orientation_forbidden", "outside_usable_carton", "envelope_overlap", "payload_exceeded",
                    "quantity_mismatch", "insert_overlap", "insert_outside_carton", "cushion_insufficient",
                    "cushion_not_verified", "no_contact_violated", "no_contact_area_outside"}
MIN_BODY_M = 1e-6


def lining(carton, cushion):
    """Foam pads meeting a cushion requirement: floor and top pads plus four side walls.

    Returns [] when no requirement is set and None when the lining leaves no cavity.
    """
    if cushion is None:
        return []
    ix, iy, iz = carton.inner_m
    f, t, s = cushion.floor_m, cushion.top_m, cushion.sides_m
    body = iy - f - t
    if body <= MIN_BODY_M or ix - 2 * s <= MIN_BODY_M or iz - 2 * s <= MIN_BODY_M:
        return None
    m = cushion.material

    def pad(pad_id, name, dimensions, position):
        return Insert(id=pad_id, name=name, dimensions_m=dimensions, position_m=position, material=m.name,
                      density_kg_m3=m.density_kg_m3, material_evidence=m.evidence)

    pads = []
    if f > 0:
        pads.append(pad("cushion-floor", "Floor cushion", (ix, f, iz), (0.0, 0.0, 0.0)))
    if t > 0:
        pads.append(pad("cushion-top", "Top cushion", (ix, t, iz), (0.0, iy - t, 0.0)))
    if s > 0:
        pads += [pad("cushion-x-min", "Side cushion", (s, body, iz), (0.0, f, 0.0)),
                 pad("cushion-x-max", "Side cushion", (s, body, iz), (ix - s, f, 0.0)),
                 pad("cushion-z-min", "Side cushion", (ix - 2 * s, body, s), (s, f, 0.0)),
                 pad("cushion-z-max", "Side cushion", (ix - 2 * s, body, s), (s, f, iz - s))]
    return pads


def package_allowance(design):
    """(kg, evidence, basis) for every package a proposal builds."""
    rule = design.constraints.package_allowance
    if rule is not None:
        return rule.allowance_kg, rule.evidence, "rule"
    values = {(p.allowance_kg, p.allowance_evidence) for p in design.packages}
    if len(values) == 1:
        kg, evidence = next(iter(values))
        if kg is not None:
            return kg, evidence, "carried_forward"
    return None, "", "unknown"


def carton_graphics(design):
    """Carton artwork shared by every saved package is carried; anything else is reported."""
    sets = [[g for g in p.graphics if g.target == "carton"] for p in design.packages]
    if sets and sets[0] and all([g.model_dump(mode="json") for g in s] == [g.model_dump(mode="json") for g in sets[0]] for s in sets):
        return [g.model_copy(deep=True) for g in sets[0]], "carried_forward"
    return [], "not_carried" if any(sets) else "none"


def propose(design: Design, cartons, max_packages=3, deadline_seconds=10):
    from py3dbp import Packer, Bin, Item
    if not design.product:
        raise PackagingError("product_required", "Select a product before arranging packages.", 400)
    p = design.product
    c = design.constraints
    cushion = c.cushion
    if cushion is None and any(package.inserts for package in design.packages):
        raise PackagingError("protection_requirement_needed",
                             "This design has packing inserts that a new arrangement would drop. Set the minimum "
                             "cushioning so proposals rebuild protection, or remove the inserts deliberately first.", 409)
    allowance_kg, allowance_evidence, allowance_basis = package_allowance(design)
    graphics, graphics_basis = carton_graphics(design)
    dropped_insert_graphics = sum(1 for package in design.packages for g in package.graphics if g.target == "insert")
    # Air kept on both faces of every product axis with a no-contact region, so any rotation keeps it.
    reserve = [0.0, 0.0, 0.0]
    for region in c.no_contact:
        axis = FACES[region.face][0]
        reserve[axis] = max(reserve[axis], region.air_gap_m)
    start = time.monotonic()
    results, rejected = [], []

    class ConstrainedItem(Item):
        def get_dimension(self):
            if self.rotation_type not in c.allowed_orientations:
                return [Decimal("1000000000")] * 3
            return super().get_dimension()

    def finish(truncated):
        results.sort(key=lambda x: (x["package_count"], x["shipping_volume_m3"]))
        return {"candidates": results[:6], "truncated": truncated, "algorithm": "py3dbp-1.1.2",
                "elapsed_ms": round((time.monotonic() - start) * 1000), "rejected": rejected[:6],
                "preservation": {"cushion": "rebuilt_from_requirement" if cushion else "not_required",
                                 "allowance": allowance_basis, "carton_graphics": graphics_basis,
                                 "insert_graphics_dropped": dropped_insert_graphics,
                                 "no_contact": "air_gap_reserved" if c.no_contact else "not_required"},
                "notice": "Feasible envelope arrangements, not a global optimum or a protective-performance rating. "
                          + ("Each candidate rebuilds the required foam lining. " if cushion else "No cushion requirement is set. ")
                          + ("No-contact air gaps are kept clear around every product. " if c.no_contact else "")
                          + ("Packing allowances are unknown until confirmed." if allowance_basis == "unknown"
                             else "Confirm packing allowances before quoting.")}

    for carton in cartons:
        pads = lining(carton, cushion)
        if pads is None:
            rejected.append({"carton": carton.name, "reason": "lining_leaves_no_cavity"})
            continue
        side, floor, top = (cushion.sides_m, cushion.floor_m, cushion.top_m) if cushion else (0.0, 0.0, 0.0)
        lower = (max(c.clearance_m, side), max(c.clearance_m, floor), max(c.clearance_m, side))
        upper = (carton.inner_m[0] - lower[0], carton.inner_m[1] - max(c.clearance_m, top), carton.inner_m[2] - lower[2])
        usable = [upper[k] - lower[k] + c.gap_m for k in range(3)]
        if min(usable) <= 0:
            rejected.append({"carton": carton.name, "reason": "no_usable_space"})
            continue
        pad_kg = sum(math.prod(x.dimensions_m) * x.density_kg_m3 for x in pads)
        capacity = None if carton.max_payload_kg is None else carton.max_payload_kg - pad_kg - (allowance_kg or 0)
        if capacity is not None and capacity <= 0:
            rejected.append({"carton": carton.name, "reason": "payload_used_by_packing"})
            continue
        found = False
        for num in range(1, max_packages + 1):
            if time.monotonic() - start > deadline_seconds:
                return finish(True)
            packer = Packer()
            for b in range(num):
                packer.add_bin(Bin(f"box_{b + 1}", *(x * 1000 for x in usable), 1000 if capacity is None else capacity))
            for i in range(design.quantity):
                packer.add_item(ConstrainedItem(f"item_{i + 1}", *((x + 2 * reserve[k] + c.gap_m) * 1000 for k, x in enumerate(p.dimensions_m)),
                                                p.mass_kg or 0))
            packer.pack(distribute_items=True, number_of_decimals=3)
            if packer.items:
                continue
            candidate = design.model_copy(deep=True)
            candidate.packages = [Package(
                id=b.name, carton=carton.model_copy(deep=True),
                placements=[Placement(id=i.name, position_m=tuple(round(float(x) / 1000 + lower[k] + reserve[ORDERS[i.rotation_type][k]], 9)
                                                         for k, x in enumerate(i.position)),
                                      orientation=i.rotation_type) for i in b.items],
                inserts=[x.model_copy(deep=True) for x in pads],
                allowance_kg=allowance_kg, allowance_evidence=allowance_evidence,
                graphics=[g.model_copy(deep=True) for g in graphics]) for b in packer.bins if b.items]
            assessment = assess(candidate)
            failed = sorted({f["code"] for f in assessment["findings"]} & GEOMETRIC_ERRORS)
            if failed:
                rejected.append({"carton": carton.name, "reason": "validation_failed", "packages": num, "codes": failed[:4]})
                continue
            results.append({"candidate_id": "candidate_" + digest(candidate)[:20], "design": candidate.model_dump(mode="json"), "assessment": assessment,
                            "package_count": len(candidate.packages), "shipping_volume_m3": sum(x.carton.outer_m[0] * x.carton.outer_m[1] * x.carton.outer_m[2] for x in candidate.packages)})
            found = True
            break
        if not found and not any(r["carton"] == carton.name and r["reason"] == "validation_failed" for r in rejected):
            rejected.append({"carton": carton.name, "reason": "does_not_fit", "packages": max_packages})
    return finish(False)
