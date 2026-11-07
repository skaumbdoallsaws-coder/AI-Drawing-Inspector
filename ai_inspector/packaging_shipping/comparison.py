"""Deterministic cost comparison of designs against a user-selected baseline.

Only saved quotes are read; nothing here contacts a provider. A design is ranked only when it
keeps the baseline's product, quantity, constraints, protection, packing allowance and payload
evidence, passes validation, and has a quote with the exact fingerprint for the same scenario and
carrier account in the same mode. Prices use the account rate only; list and retail rates are
never mixed in. Money is Decimal throughout, and unknown costs stay unknown, never zero.
"""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from .rating import quote_fingerprint

CENT = Decimal("0.01")
KG = 1e-9

REASONS = {
    "validation_failed": "Validation reports errors, so this design cannot be rated or compared.",
    "product_changed": "The product geometry, mass or source differs from the baseline.",
    "quantity_changed": "The quantity or number of placed products differs from the baseline.",
    "constraints_changed": "Protection, orientation, clearance or contents constraints differ from the baseline.",
    "protection_reduced": "It has less insert material than the baseline, and no cushion requirement is set to check it.",
    "allowance_reduced": "A package carries a smaller packing allowance than the baseline.",
    "payload_unverified": "A carton has no payload limit, but every baseline carton has one.",
    "not_quoted": "No saved quote matches this design, scenario and carrier account.",
    "mode_mismatch": "Its quote mode (test or production) differs from the baseline quote.",
    "service_unavailable": "The selected service was not quoted for every destination.",
    "baseline_not_ready": "The baseline itself cannot be compared, so no differences are shown.",
}
CAVEATS = {
    "test_mode": "Test-mode quotes are not live carrier prices; no saving is claimed.",
    "materials_unknown": "Material cost is unknown and is left out of the total.",
    "payload_unknown": "At least one carton has no declared payload limit.",
    "parcel_sum": "Multi-package prices are sums of separate parcel estimates, not a consolidated shipment quote.",
    "currency_differs": "Shipping and material costs use different currencies, so there is no combined total.",
    "quote_dates_differ": "This design and the baseline were quoted more than 24 hours apart; carrier prices may have changed in between.",
}
NOTICE = ("Compared on the account rate only, for the same scenario, carrier account, mode and service. Shipping is the "
          "sum across the quoted destinations. Unknown costs are left out, never counted as zero. These are feasible "
          "envelope arrangements and estimates, not a protective-performance rating or a price guarantee.")


def _identity(design):
    p = design.product
    return None if p is None else (tuple(p.dimensions_m), p.mass_kg, p.mass_basis, p.source_id, p.source_revision)


def _insert_kg(assessment):
    values = [p["insert_kg"] for p in assessment["packages"]]
    return None if any(v is None for v in values) else sum(values)


def _allowance_floor(design):
    rule = design.constraints.package_allowance
    if rule is not None:
        return rule.allowance_kg
    values = [p.allowance_kg for p in design.packages]
    return min(values) if values and all(v is not None for v in values) else None


def integrity(baseline, candidate):
    """Reasons a candidate cannot be compared with the baseline; empty when it keeps every input."""
    b, c = baseline["design"], candidate["design"]
    reasons = []
    if not candidate["assessment"]["rate_ready"]:
        reasons.append("validation_failed")
    if _identity(c) != _identity(b):
        reasons.append("product_changed")
    if c.quantity != b.quantity or candidate["assessment"]["placed_quantity"] != baseline["assessment"]["placed_quantity"]:
        reasons.append("quantity_changed")
    if c.constraints != b.constraints:
        reasons.append("constraints_changed")
    if b.constraints.cushion is None and any(p.inserts for p in b.packages):
        # Without a cushion requirement there is no geometric check, so protection may not shrink.
        base_kg, kg = _insert_kg(baseline["assessment"]), _insert_kg(candidate["assessment"])
        if base_kg is None or kg is None or kg < base_kg - KG:
            reasons.append("protection_reduced")
    floor = _allowance_floor(b)
    if floor is not None and any(p.allowance_kg is None or p.allowance_kg < floor - KG for p in c.packages):
        reasons.append("allowance_reduced")
    if (b.packages and all(p.carton.max_payload_kg is not None for p in b.packages)
            and any(p.carton.max_payload_kg is None for p in c.packages)):
        reasons.append("payload_unverified")
    return reasons


def _key(total):
    return (total["carrier"], total["service"], total["account_id"], total["currency"])


def _service(key):
    return {"carrier": key[0], "service": key[1], "account_id": key[2], "currency": key[3]}


def _destinations(quote, key):
    """[(destination, amount)] for this service, or None when any destination lacks it."""
    rows = []
    for result in quote["results"]:
        match = next((t for t in result["totals"] if _key(t) == key), None)
        if match is None:
            return None
        rows.append((result["destination"], Decimal(match["amount"])))
    return rows or None


def _materials(assessment):
    values = [p["materials_cost_usd"] for p in assessment["packages"]]
    if not values or any(v is None for v in values):
        return None
    return sum((Decimal(str(v)) for v in values), Decimal(0)).quantize(CENT)


def _hours_apart(a, b):
    return abs((datetime.fromisoformat(a) - datetime.fromisoformat(b)).total_seconds()) / 3600


def _place(destination):
    return f"{destination['city']}, {destination['state']} {destination['zip']}"


def compare(baseline_ref, candidates, quotes, scenario_hash, account_ref, service=None):
    """candidates: [{"ref", "name", "design", "assessment"}] in display order, including the baseline.
    quotes: {fingerprint: saved quote}. service: (carrier, service, account_id, currency) or None for the
    baseline's cheapest common service."""
    baseline = next(c for c in candidates if c["ref"] == baseline_ref)

    def quote_for(candidate):
        return quotes.get(quote_fingerprint(candidate["assessment"]["design_hash"], scenario_hash, account_ref))

    base_quote = quote_for(baseline)
    services = []
    if base_quote is not None and base_quote["results"]:
        common = set.intersection(*({_key(t) for t in r["totals"]} for r in base_quote["results"]))
        for key in common:
            amount = sum((a for _, a in _destinations(base_quote, key)), Decimal(0))
            services.append({**_service(key), "baseline_amount": str(amount)})
        services.sort(key=lambda s: (Decimal(s["baseline_amount"]), s["carrier"], s["service"], s["account_id"], s["currency"]))
    if service is None and services:
        service = (services[0]["carrier"], services[0]["service"], services[0]["account_id"], services[0]["currency"])

    rows = []
    for order, candidate in enumerate(candidates):
        design, assessment = candidate["design"], candidate["assessment"]
        reasons, caveats = integrity(baseline, candidate), []
        quote, shipping = quote_for(candidate), None
        if quote is None:
            reasons.append("not_quoted")
        else:
            if base_quote is not None and quote.get("mode") != base_quote.get("mode"):
                reasons.append("mode_mismatch")
            if quote.get("mode") != "production":
                caveats.append("test_mode")
            shipping = _destinations(quote, service) if service else None
            if shipping is None:
                reasons.append("service_unavailable")
            if base_quote is not None and quote is not base_quote and _hours_apart(quote["quoted_at"], base_quote["quoted_at"]) > 24:
                caveats.append("quote_dates_differ")
        if len(design.packages) > 1:
            caveats.append("parcel_sum")
        materials = _materials(assessment)
        if materials is None:
            caveats.append("materials_unknown")
        if any(p.carton.max_payload_kg is None for p in design.packages):
            caveats.append("payload_unknown")
        shipping_total = None if shipping is None else sum((a for _, a in shipping), Decimal(0))
        total = None
        if shipping_total is not None and materials is not None:
            if service[3] == "USD":
                total = shipping_total + materials
            else:
                caveats.append("currency_differs")
        rows.append({"ref": candidate["ref"], "name": candidate["name"], "baseline": candidate["ref"] == baseline_ref,
                     "order": order, "design_hash": assessment["design_hash"], "package_count": len(design.packages),
                     "placed_quantity": assessment["placed_quantity"], "gross_kg": assessment["total_gross_kg"],
                     "outer_volume_m3": sum(p.carton.outer_m[0] * p.carton.outer_m[1] * p.carton.outer_m[2] for p in design.packages),
                     "quote": None if quote is None else {"id": quote.get("id"), "quoted_at": quote["quoted_at"], "mode": quote.get("mode")},
                     "destinations": None if shipping is None else [{"destination": d, "amount": str(a)} for d, a in shipping],
                     "shipping_total": None if shipping_total is None else str(shipping_total),
                     "materials_usd": None if materials is None else str(materials),
                     "total": None if total is None else str(total),
                     "reasons": reasons, "caveats": caveats, "eligible": False,
                     "shipping_difference": None, "total_difference": None, "claim": None})

    base_row = next(r for r in rows if r["baseline"])
    ready = not base_row["reasons"]
    production = ready and base_quote.get("mode") == "production"
    for row in rows:
        if not ready and not row["baseline"]:
            row["reasons"].append("baseline_not_ready")
        row["eligible"] = ready and not row["reasons"]
        if not row["eligible"] or row["baseline"]:
            continue
        difference = Decimal(row["shipping_total"]) - Decimal(base_row["shipping_total"])
        row["shipping_difference"] = str(difference)
        if row["total"] is not None and base_row["total"] is not None:
            row["total_difference"] = str(Decimal(row["total"]) - Decimal(base_row["total"]))
        if production and difference < 0:
            places = [_place(d["destination"]) for d in row["destinations"]]
            row["claim"] = {
                "baseline": base_row["name"], "baseline_ref": base_row["ref"], "baseline_quoted_at": base_row["quote"]["quoted_at"],
                "quoted_at": row["quote"]["quoted_at"], "account_ref": account_ref, **_service(service),
                "destinations": places, "shipping_saving": str(-difference),
                "text": (f"{row['name']} is {service[3]} {-difference} lower than baseline {base_row['name']} for "
                         f"{service[0]} {service[1]} (account {service[2] or 'not provided'}) to {'; '.join(places)}. "
                         f"Quoted {row['quote']['quoted_at']}; baseline quoted {base_row['quote']['quoted_at']}.")}
    ranked = sorted((r for r in rows if r["eligible"]),
                    key=lambda r: (Decimal(r["shipping_total"]), r["package_count"], r["outer_volume_m3"], r["gross_kg"] or 0, r["order"]))
    used = {code for r in rows for code in r["reasons"]}
    noted = {code for r in rows for code in r["caveats"]}
    return {"baseline": {"ref": base_row["ref"], "name": base_row["name"], "ready": ready, "reasons": base_row["reasons"],
                         "quote": base_row["quote"]},
            "scenario_hash": scenario_hash, "account_ref": account_ref, "price_basis": "amount",
            "service": None if service is None else _service(service), "services": services,
            "rows": rows, "ranking": [r["ref"] for r in ranked], "savings_claimed": production,
            "reasons": {k: REASONS[k] for k in sorted(used)}, "caveats": {k: CAVEATS[k] for k in sorted(noted)},
            "notice": NOTICE}


def scenarios(quotes, account_ref):
    """Distinct quoted scenarios, newest first, labelled without street addresses."""
    groups = {}
    for quote in quotes.values():
        entry = groups.setdefault(quote["scenario_hash"], {
            "scenario_hash": quote["scenario_hash"], "destinations": [r["destination"] for r in quote["results"]],
            "request": quote.get("request"), "quoted_at": quote["quoted_at"], "modes": set(), "quotes": 0,
            "current_account": False})
        entry["quotes"] += 1
        entry["modes"].add(quote.get("mode"))
        entry["current_account"] |= quote.get("account_ref") == account_ref
        if quote["quoted_at"] > entry["quoted_at"]:
            entry["quoted_at"] = quote["quoted_at"]
    out = [{**g, "modes": sorted(m for m in g["modes"] if m)} for g in groups.values()]
    out.sort(key=lambda g: g["quoted_at"], reverse=True)
    return out
