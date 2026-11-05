"""Bounded py3dbp search; every candidate is independently revalidated."""
from __future__ import annotations

from decimal import Decimal
import time
from .geometry import assess, digest
from .models import Design, Package, Placement
from .service import PackagingError


def propose(design: Design, cartons, max_packages=3, deadline_seconds=10):
    from py3dbp import Packer, Bin, Item
    if not design.product:
        raise PackagingError("product_required", "Select a product before arranging packages.", 400)
    p = design.product
    c = design.constraints
    start = time.monotonic()
    results = []

    class ConstrainedItem(Item):
        def get_dimension(self):
            if self.rotation_type not in c.allowed_orientations:
                return [Decimal("1000000000")] * 3
            return super().get_dimension()

    for carton in cartons:
        usable = [i - 2 * c.clearance_m + c.gap_m for i in carton.inner_m]
        if min(usable) <= 0:
            continue
        for num in range(1, max_packages + 1):
            if time.monotonic() - start > deadline_seconds:
                return {"candidates": results[:6], "truncated": True, "algorithm": "py3dbp-1.1.2", "elapsed_ms": round((time.monotonic() - start) * 1000)}
            packer = Packer()
            for b in range(num):
                packer.add_bin(Bin(f"box_{b + 1}", *(x * 1000 for x in usable), carton.max_payload_kg or 1000))
            for i in range(design.quantity):
                packer.add_item(ConstrainedItem(f"item_{i + 1}", *((x + c.gap_m) * 1000 for x in p.dimensions_m), p.mass_kg or 0))
            packer.pack(distribute_items=True, number_of_decimals=3)
            if packer.items:
                continue
            candidate = design.model_copy(deep=True)
            candidate.packages = [Package(id=b.name, carton=carton.model_copy(deep=True),
                placements=[Placement(id=i.name, position_m=tuple(round(float(x) / 1000 + c.clearance_m, 9) for x in i.position), orientation=i.rotation_type) for i in b.items]) for b in packer.bins if b.items]
            assessment = assess(candidate)
            geometric_errors = {"orientation_forbidden", "outside_usable_carton", "envelope_overlap", "payload_exceeded", "quantity_mismatch"}
            if any(f["code"] in geometric_errors for f in assessment["findings"]):
                continue
            results.append({"candidate_id": "candidate_" + digest(candidate)[:20], "design": candidate.model_dump(mode="json"), "assessment": assessment,
                            "package_count": len(candidate.packages), "shipping_volume_m3": sum(x.carton.outer_m[0] * x.carton.outer_m[1] * x.carton.outer_m[2] for x in candidate.packages)})
            break
    results.sort(key=lambda x: (x["package_count"], x["shipping_volume_m3"]))
    return {"candidates": results[:6], "truncated": False, "algorithm": "py3dbp-1.1.2", "elapsed_ms": round((time.monotonic() - start) * 1000),
            "notice": "Feasible envelope arrangements, not a global optimum. Add and validate protective packing and confirm all mass allowances before quoting."}
